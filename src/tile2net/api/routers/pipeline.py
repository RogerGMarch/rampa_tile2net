"""Pipeline lifecycle — trigger, status, cancel."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from tile2net.api.deps import get_registry_db, read_project, update_project_status
from tile2net.api.models import (
    PipelineStage,
    TaskInfo,
    get_task,
    register_task,
)
from tile2net.api.schemas import (
    PipelineCancelResponse,
    PipelineStatus,
    PipelineTrigger,
)

router = APIRouter()


def _task_to_status(task: TaskInfo) -> PipelineStatus:
    return PipelineStatus(
        task_id=task.task_id,
        project_name=task.project_name,
        status=task.status,
        stage=task.stage.value if task.stage else None,
        progress=task.progress,
        message=task.message or None,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
    )


# ── stage runners (called in thread pool) ──────────────────────────────────────

def _build_generate_script(source_row: dict, generate_args: list[str]) -> str:
    script = f'''import sys
from tile2net.api.deps import register_source_runtime

register_source_runtime({json.dumps(source_row)})

sys.argv = ["tile2net", "generate"] + {json.dumps(generate_args)}
from tile2net.__main__ import main
main()
'''
    fd, path = tempfile.mkstemp(suffix=".py", prefix="tile2net_generate_")
    with os.fdopen(fd, 'w') as f:
        f.write(script)
    return path


def _run_generate(project: dict, task: TaskInfo, trigger: PipelineTrigger):
    bbox = (
        f"{project['bbox_s']},{project['bbox_w']},"
        f"{project['bbox_n']},{project['bbox_e']}"
    )
    generate_args = [
        "-l", bbox,
        "-n", project["name"],
        "-o", project["output_dir"],
        "-z", str(project["zoom"]),
    ]

    if trigger.tile_input_dir:
        generate_args += ["--input", trigger.tile_input_dir]

    source_name = project.get("source")
    custom_source = None
    if source_name:
        from tile2net.api.deps import get_registry_db, read_source
        con = get_registry_db()
        try:
            custom_source = read_source(con, source_name)
        finally:
            con.close()
        generate_args += ["-s", source_name]

    if custom_source:
        script_path = _build_generate_script(custom_source, generate_args)
        try:
            cmd = [sys.executable, script_path]
            task.message = "Downloading tiles and stitching..."
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        finally:
            os.unlink(script_path)
    else:
        cmd = [sys.executable, "-m", "tile2net", "generate"] + generate_args
        task.message = "Downloading tiles and stitching..."
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

    if result.returncode != 0:
        raise RuntimeError(f"Generate failed: {result.stderr[:5000]}")
    return result.stdout


def _run_inference(project: dict, info_json: str, task: TaskInfo):
    task.message = "Running semantic segmentation..."
    cmd = [sys.executable, "-m", "tile2net", "inference"]
    result = subprocess.run(
        cmd, input=info_json, capture_output=True, text=True, timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Inference failed: {result.stderr[:500]}")


def _run_postprocess(project: dict, task: TaskInfo):
    from tile2net.postprocess import (
        OSMViarioSource,
        OfficialViarioSource,
        PedestrianPostProcessor,
        PostProcessConfig,
    )

    task.message = "Post-processing polygons (steps 1-10)..."
    output_dir = Path(project["output_dir"]) / project["name"]
    poly_path = output_dir / "polygons" / "final" / "final.shp"

    net_dirs = sorted((output_dir / "network").iterdir())
    if not net_dirs:
        raise RuntimeError("No network directory found in inference output")
    net_dir = net_dirs[-1]
    net_path = net_dir / f"{net_dir.name}.shp"

    if project.get("viario_type") == "official" and project.get("viario_url"):
        viario = OfficialViarioSource(
            source_type="arcgis_rest",
            url=project["viario_url"],
        )
    else:
        viario = OSMViarioSource(
            cache_path=Path(project["output_dir"]) / "osm_cache.json"
        )

    cfg = PostProcessConfig(
        metric_crs=project.get("metric_crs", "EPSG:25830"),
    )

    proc = PedestrianPostProcessor(
        polygon_path=poly_path,
        network_path=net_path,
        viario=viario,
        config=cfg,
    )
    task.message = "Post-processing — running pipeline..."
    result = proc.run()
    task.message = "Saving results..."
    result.save(str(output_dir))
    task._result = result
    task.progress = 0.99


def _run_persist(project: dict, task: TaskInfo):
    from tile2net.duckdb import (
        get_duckdb_connection,
        write_graph,
        write_network,
        write_polygons,
    )

    task.message = "Persisting to DuckDB..."
    output_dir = Path(project["output_dir"]) / project["name"]
    db_path = output_dir / "tile2net.db"
    con = get_duckdb_connection(db_path)

    result = task._result
    write_polygons(con, project["name"], result.polygons)
    write_network(con, project["name"], result.network)
    write_graph(con, project["name"], result.graph)
    con.close()
    task.progress = 1.0


# ── async wrapper ──────────────────────────────────────────────────────────────

async def _run_pipeline(project: dict, task: TaskInfo, trigger: PipelineTrigger):
    try:
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)

        if not trigger.skip_generate:
            task.stage = PipelineStage.GENERATING
            task.progress = 0.05
            info_json = await asyncio.to_thread(_run_generate, project, task, trigger)
            task.progress = 0.33
            con = get_registry_db()
            try:
                update_project_status(con, project["name"], "generating")
            finally:
                con.close()
        else:
            output_dir = Path(project["output_dir"]) / project["name"]
            struct_path = output_dir / "structure.json"
            if struct_path.exists():
                with open(struct_path) as f:
                    info_json = f.read()
            else:
                info_json = json.dumps({"name": project["name"]})
            task.progress = 0.33

        task.stage = PipelineStage.INFERRING
        task.progress = 0.35
        await asyncio.to_thread(_run_inference, project, info_json, task)
        task.progress = 0.66
        con = get_registry_db()
        try:
            update_project_status(con, project["name"], "inferring")
        finally:
            con.close()

        if not trigger.skip_postprocess:
            task.stage = PipelineStage.POSTPROCESSING
            task.progress = 0.68
            await asyncio.to_thread(_run_postprocess, project, task)
            await asyncio.to_thread(_run_persist, project, task)

        task.status = "completed"
        task.progress = 1.0
        task.stage = None
        task.message = "Pipeline completed successfully"
        con = get_registry_db()
        try:
            update_project_status(con, project["name"], "completed")
        finally:
            con.close()

    except asyncio.CancelledError:
        task.status = "cancelled"
        task.message = "Pipeline cancelled by user"
        con = get_registry_db()
        try:
            update_project_status(con, project["name"], "failed")
        finally:
            con.close()
    except Exception as exc:
        task.status = "failed"
        task.error = traceback.format_exc()
        task.message = str(exc)[:500]
        con = get_registry_db()
        try:
            update_project_status(con, project["name"], "failed")
        finally:
            con.close()
    finally:
        task.finished_at = datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/{name}/pipeline",
    status_code=201,
    response_model=PipelineStatus,
    summary="Start the processing pipeline",
    responses={
        404: {"description": "Project not found"},
        409: {"description": "Pipeline already running for this project"},
        400: {"description": "Cannot skip generate without a prior bbox"},
    },
)
async def trigger_pipeline(name: str, trigger: PipelineTrigger = PipelineTrigger()):
    """Launch the full pipeline for a project.

    The pipeline runs **asynchronously** in the background:

    1. **generate**  — downloads and stitches aerial-imagery tiles
    2. **infer**     — runs semantic segmentation (HRNet + OCRNet)
    3. **postprocess** — cleans polygons, gap-fills via OSM, estimates widths, builds graph
    4. **persist**   — writes polygons, network, and graph into DuckDB

    Use ``GET /projects/{name}/pipeline/status`` to track progress (polling).
    """
    con = get_registry_db()
    try:
        project = read_project(con, name)
    finally:
        con.close()

    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")

    existing = get_task(name)
    if existing and existing.status in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline already running for project {name!r}",
        )

    if trigger.skip_generate and project.get("status") != "completed":
        bbox_cols = ("bbox_s", "bbox_w", "bbox_n", "bbox_e")
        if not all(project.get(c) is not None for c in bbox_cols):
            raise HTTPException(
                status_code=400,
                detail="Cannot skip generate: project has no bbox set",
            )

    task = register_task(name)
    asyncio.create_task(_run_pipeline(project, task, trigger))
    return _task_to_status(task)


@router.get(
    "/{name}/pipeline/status",
    response_model=PipelineStatus,
    summary="Get pipeline status",
    responses={404: {"description": "No pipeline found for this project"}},
)
def pipeline_status(name: str):
    """Return the current status of the pipeline for *name*.

    Includes progress (0.0–1.0), current stage, and any error message.
    Poll this endpoint while the pipeline is running.
    """
    task = get_task(name)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"No pipeline found for project {name!r}",
        )
    return _task_to_status(task)


@router.delete(
    "/{name}/pipeline",
    response_model=PipelineCancelResponse,
    summary="Cancel a running pipeline",
    responses={
        404: {"description": "No pipeline found for this project"},
        400: {"description": "Pipeline is not in a cancellable state"},
    },
)
def cancel_pipeline(name: str):
    """Request cancellation of a running pipeline.

    Cancellation is **best-effort**: the current stage is allowed to finish
    before the pipeline stops.  The task status transitions to ``cancelled``.
    """
    task = get_task(name)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"No pipeline found for project {name!r}",
        )
    if task.status not in ("queued", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline is not running (status: {task.status})",
        )
    task._cancel.set()
    return PipelineCancelResponse(task_id=task.task_id, cancelled=True)
