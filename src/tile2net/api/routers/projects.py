"""Project CRUD endpoints."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from tile2net.api.config import get_api_config
from tile2net.api.deps import (
    create_project as _create_project,
    delete_project as _delete_project,
    get_registry_db,
    list_projects as _list_projects,
    read_project as _read_project,
    update_project_fields as _update_project_fields,
    update_project_status,
)
from tile2net.api.models import get_task
from tile2net.api.schemas import (
    PipelineProjectInfo,
    ProjectCreate,
    ProjectDeleteResponse,
    ProjectInfo,
    ProjectList,
    ProjectPatch,
)
from tile2net.api.utils import bbox_from_location

router = APIRouter()


def _pipeline_info(project_name: str) -> PipelineProjectInfo | None:
    task = get_task(project_name)
    if task is None:
        return None
    return PipelineProjectInfo(
        task_id=task.task_id,
        status=task.status,
        stage=task.stage.value if task.stage else None,
        progress=task.progress,
        message=task.message or None,
    )


def _to_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    return None


def _project_to_info(row: dict) -> ProjectInfo:
    bbox = None
    if all(row.get(k) is not None for k in ("bbox_s", "bbox_w", "bbox_n", "bbox_e")):
        bbox = [row["bbox_s"], row["bbox_w"], row["bbox_n"], row["bbox_e"]]
    return ProjectInfo(
        name=row["name"],
        location=row["location"],
        zoom=int(row["zoom"]),
        crs=int(row["crs"]),
        metric_crs=row["metric_crs"],
        viario_type=row["viario_type"],
        status=row["status"],
        bbox_wgs84=bbox,
        created_at=_to_dt(row.get("created_at")),
        updated_at=_to_dt(row.get("updated_at")),
        pipeline=_pipeline_info(row["name"]),
    )


@router.post(
    "/",
    status_code=201,
    response_model=ProjectInfo,
    summary="Register a new city project",
    responses={
        409: {"description": "A project with this name already exists"},
        400: {"description": "Invalid location string — cannot be geocoded"},
    },
)
def create_project_endpoint(data: ProjectCreate):
    """Register a new city project in the registry.

    The ``location`` is geocoded to a WGS84 bounding box.  A directory
    structure (``tiles/``, ``polygons/``, ``network/``) is created on disk.
    The project starts in **created** status — call the pipeline endpoint
    to begin processing.
    """
    cfg = get_api_config()
    con = get_registry_db()
    try:
        existing = _read_project(con, data.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Project {data.name!r} already exists",
            )
        try:
            bbox = bbox_from_location(data.location)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        output_dir = str(cfg.data_root / "projects" / data.name)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        for sub in ("tiles", "polygons", "network"):
            (Path(output_dir) / sub).mkdir(exist_ok=True)

        row = {
            "name": data.name,
            "location": data.location,
            "zoom": data.zoom,
            "crs": data.crs,
            "metric_crs": data.metric_crs,
            "source": data.source,
            "tile_step": data.tile_step,
            "stitch_step": data.stitch_step,
            "viario_type": data.viario_type,
            "viario_url": data.viario_url,
            "output_dir": output_dir,
        }
        _create_project(con, row)
        update_project_status(con, data.name, "created", bbox)
        row = _read_project(con, data.name)
        return _project_to_info(row)
    finally:
        con.close()


@router.get(
    "/",
    response_model=ProjectList,
    summary="List all projects",
)
def list_projects_endpoint(status: str | None = None):
    """Return all registered projects, newest first.

    Optionally filter by *status* (e.g. ``completed``, ``failed``, ``created``).
    """
    con = get_registry_db()
    try:
        rows = _list_projects(con, status)
        return ProjectList(projects=[_project_to_info(r) for r in rows])
    finally:
        con.close()


@router.get(
    "/{name}",
    response_model=ProjectInfo,
    summary="Get a single project",
    responses={404: {"description": "Project not found"}},
)
def get_project_endpoint(name: str):
    """Return full metadata for *name*, including its current pipeline status
    if a pipeline has been run.
    """
    con = get_registry_db()
    try:
        row = _read_project(con, name)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {name!r} not found")
        return _project_to_info(row)
    finally:
        con.close()


@router.patch(
    "/{name}",
    response_model=ProjectInfo,
    summary="Update a project",
    responses={404: {"description": "Project not found"}},
)
def patch_project_endpoint(name: str, data: ProjectPatch):
    """Update mutable fields (*metric_crs*, *viario_type*, *viario_url*).

    The project name and location cannot be changed after creation.
    """
    con = get_registry_db()
    try:
        row = _read_project(con, name)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {name!r} not found")
        updates = {}
        for k, v in data.model_dump(exclude_unset=True).items():
            if v is not None:
                updates[k] = v
        if updates:
            _update_project_fields(con, name, **updates)
        row = _read_project(con, name)
        return _project_to_info(row)
    finally:
        con.close()


@router.delete(
    "/{name}",
    response_model=ProjectDeleteResponse,
    summary="Delete a project",
    responses={404: {"description": "Project not found"}},
)
def delete_project_endpoint(name: str):
    """Delete a project and all its data.

    Cancels any running pipeline, removes the registry entry, and deletes the
    project directory (tiles, polygons, network, DuckDB) from disk.
    """
    from tile2net.api.models import _project_task as pt, _tasks as ts

    con = get_registry_db()
    try:
        row = _read_project(con, name)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project {name!r} not found")

        tid = pt.pop(name, None)
        if tid:
            task = ts.pop(tid, None)
            if task:
                task._cancel.set()

        _delete_project(con, name)

        output_dir = Path(row["output_dir"])
        if output_dir.exists():
            shutil.rmtree(output_dir)

        return {"name": name, "deleted": True}
    finally:
        con.close()
