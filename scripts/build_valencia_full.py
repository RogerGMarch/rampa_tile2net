#!/usr/bin/env python3
"""Build full Valencia pedestrian graph at zoom 20 with checkpoint/resume.

Splits the Valencia municipal bbox into a 6×6 grid, processes each cell
independently (generate → inference → postprocess), and merges sub-graphs.

Usage:
    uv run python scripts/build_valencia_full.py

Checkpoint file:
    ~/.tile2net/projects/valencia_full_z20_grid/checkpoint.json
"""

from __future__ import annotations

import glob
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
import traceback
import warnings
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import box, LineString

# ────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────

GRID_SIZE = 6
ZOOM = 20
STITCH_STEP = 4
TILE_STEP = 1
BASE_TILESIZE = 256
METRIC_CRS = "EPSG:25830"

OUTPUT_ROOT = Path.home() / ".tile2net" / "projects" / "valencia_full_z20_grid"
CHECKPOINT_PATH = OUTPUT_ROOT / "checkpoint.json"
FINAL_GPICKLE = OUTPUT_ROOT / "valencia_full_z20.gpickle"
FINAL_GRAPHML = OUTPUT_ROOT / "valencia_full_z20.graphml"

ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

# ────────────────────────────────────────────────────────────────
# Checkpoint helpers
# ────────────────────────────────────────────────────────────────


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {"completed": [], "in_progress": None, "cell_graphs": {}}


def save_checkpoint(ck: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(ck, indent=2))


def mark_cell_start(ck: dict, row: int, col: int, step: str) -> None:
    ck["in_progress"] = {"row": row, "col": col, "step": step}
    save_checkpoint(ck)


def mark_cell_done(ck: dict, row: int, col: int, graph_path: str) -> None:
    ck["completed"].append({"row": row, "col": col})
    key = f"{row}_{col}"
    ck["cell_graphs"][key] = graph_path
    ck["in_progress"] = None
    save_checkpoint(ck)


def is_cell_done(ck: dict, row: int, col: int) -> bool:
    key = f"{row}_{col}"
    return key in ck["cell_graphs"]


def get_resume_cell(ck: dict) -> tuple | None:
    ip = ck.get("in_progress")
    if ip is None:
        return None
    return (int(ip["row"]), int(ip["col"]), ip.get("step", "generate"))


# ────────────────────────────────────────────────────────────────
# Step 1: Geocode Valencia
# ────────────────────────────────────────────────────────────────


def get_valencia_bbox() -> tuple[float, float, float, float]:
    import osmnx as ox

    print("[1/5] Geocoding 'Valencia, Spain' via Nominatim...")
    gdf = ox.geocode_to_gdf("Valencia, Spain")
    w, s, e, n = gdf.total_bounds
    print(f"  Bbox (W,S,E,N): {w:.6f}, {s:.6f}, {e:.6f}, {n:.6f}")
    print(f"  Area: ~{(e - w) * 111:.1f}km × {(n - s) * 111:.1f}km")
    return float(s), float(w), float(n), float(e)


# ────────────────────────────────────────────────────────────────
# Step 2: Build grid
# ────────────────────────────────────────────────────────────────


def build_grid(s: float, w: float, n: float, e: float, size: int):
    lats = np.linspace(s, n, size + 1)
    lons = np.linspace(w, e, size + 1)
    print(f"\n[2/5] Grid: {size}×{size} = {size * size} cells")
    for r in range(size):
        for c in range(size):
            cell_bbox = (lats[r], lons[c], lats[r + 1], lons[c + 1])
            print(
                f"  [{r},{c}] S={cell_bbox[0]:.5f} W={cell_bbox[1]:.5f} "
                f"N={cell_bbox[2]:.5f} E={cell_bbox[3]:.5f}"
            )
    return lats, lons


# ────────────────────────────────────────────────────────────────
# Step 3: Register ESRI source
# ────────────────────────────────────────────────────────────────


def register_esri_source() -> None:
    from tile2net.api.deps import register_source_runtime

    print("\n[3/5] Registering ESRI World Imagery source...")
    source_row = {
        "name": "esri_world",
        "tile_url": ESRI_URL,
        "bbox_s": 38.0,
        "bbox_w": -1.5,
        "bbox_n": 40.5,
        "bbox_e": 1.0,
        "zoom_max": ZOOM,
        "extension": "jpg",
        "tilesize": 256,
        "server": "ESRI World Imagery",
        "keyword": "ESRI World Imagery",
    }
    register_source_runtime(source_row)
    print("  ESRI source registered in SourceMeta.catalog")


# ────────────────────────────────────────────────────────────────
# Step 4: Process one cell
# ────────────────────────────────────────────────────────────────


def find_latest_dir(parent: Path, pattern: str) -> Path | None:
    matches = sorted(parent.glob(pattern))
    if not matches:
        return None
    return matches[-1]


def run_inference(info_json_path: Path, interactive: bool = True) -> None:
    cmd = [
        sys.executable,
        "-m",
        "tile2net",
        "inference",
        "--city_info",
        str(info_json_path),
        "--dump_percent",
        "0",
    ]
    if interactive:
        cmd.append("--interactive")
    print(f"  Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def process_cell(
    row: int,
    col: int,
    cell_bbox: list[float],
    cell_name: str,
    ck: dict,
) -> dict:
    from tile2net.postprocess import PedestrianPostProcessor, PostProcessConfig
    from tile2net.raster.raster import Raster

    cell_dir = OUTPUT_ROOT / cell_name
    cell_dir.mkdir(parents=True, exist_ok=True)

    resume_step = None
    ip = ck.get("in_progress")
    if ip and ip["row"] == row and ip["col"] == col:
        resume_step = ip.get("step")
        print(f"  Resuming from step: {resume_step}")

    # ---- 4a. Generate tiles ----
    if resume_step is None or resume_step == "generate":
        mark_cell_start(ck, row, col, "generate")
        print(f"  [{row},{col}] Generate: creating tile grid...")
        t0 = time.time()

        raster = Raster(
            location=cell_bbox,
            name=cell_name,
            zoom=ZOOM,
            source="esri_world",
            output_dir=str(OUTPUT_ROOT),
            tile_step=TILE_STEP,
            base_tilesize=BASE_TILESIZE,
        )
        raster.generate(step=STITCH_STEP)

        elapsed = time.time() - t0
        print(f"  [{row},{col}] Generate done in {elapsed:.0f}s")

        # Find the info.json path that was just written
        info_path = Path(raster.project.tiles.info.__fspath__())
    else:
        raster = Raster(
            location=cell_bbox,
            name=cell_name,
            zoom=ZOOM,
            source="esri_world",
            output_dir=str(OUTPUT_ROOT),
            tile_step=TILE_STEP,
            base_tilesize=BASE_TILESIZE,
        )
        info_path = Path(raster.project.tiles.info.__fspath__())
        print(f"  [{row},{col}] Skipping generate (already done)")

    # ---- 4b. Inference ----
    if resume_step is None or resume_step in ("generate", "inference"):
        mark_cell_start(ck, row, col, "inference")
        print(f"  [{row},{col}] Inference: running GPU model...")
        t0 = time.time()

        run_inference(info_path)

        elapsed = time.time() - t0
        print(f"  [{row},{col}] Inference done in {elapsed:.0f}s")
    else:
        print(f"  [{row},{col}] Skipping inference (already done)")

    # Find polygon + network paths
    poly_dir = find_latest_dir(
        Path(raster.project.polygons.__fspath__()),
        f"{cell_name}-Polygons-*",
    )
    net_dir = find_latest_dir(
        Path(raster.project.network.__fspath__()),
        f"{cell_name}-Network-*",
    )

    if poly_dir is None or net_dir is None:
        raise FileNotFoundError(
            f"Could not find polygons or network for {cell_name}. "
            f"polygons_dir={poly_dir}, network_dir={net_dir}"
        )

    poly_shp = poly_dir / f"{poly_dir.name}.shp"
    net_shp = net_dir / f"{net_dir.name}.shp"

    print(f"  Polygons: {poly_shp}")
    print(f"  Network:  {net_shp}")

    # ---- 4c. Postprocess ----
    if resume_step is None or resume_step in ("generate", "inference", "postprocess"):
        mark_cell_start(ck, row, col, "postprocess")
        print(f"  [{row},{col}] Postprocess: cleaning, gap-fill, width, graph...")
        t0 = time.time()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            proc = PedestrianPostProcessor(
                polygon_path=poly_shp,
                network_path=net_shp,
                config=PostProcessConfig(metric_crs=METRIC_CRS),
            )
            result = proc.run()

        result.save(cell_dir)
        elapsed = time.time() - t0
        print(
            f"  [{row},{col}] Postprocess done in {elapsed:.0f}s "
            f"({result.graph.number_of_nodes()} nodes, "
            f"{result.graph.number_of_edges()} edges)"
        )
    else:
        print(f"  [{row},{col}] Skipping postprocess (already done)")
        import pickle as pkl

        gpath = cell_dir / "graph.gpickle"
        with open(gpath, "rb") as f:
            g = pkl.load(f)
        node_count = g.number_of_nodes()
        edge_count = g.number_of_edges()
        print(
            f"  [{row},{col}] Loaded from disk: {node_count} nodes, {edge_count} edges"
        )

    graph_path = str(cell_dir / "graph.gpickle")
    mark_cell_done(ck, row, col, graph_path)
    print(f"  [{row},{col}] Cell complete ✓")
    return {"row": row, "col": col, "graph_path": graph_path}


# ────────────────────────────────────────────────────────────────
# Step 5: Merge graphs
# ────────────────────────────────────────────────────────────────


def deduplicate_boundary_edges(graph: nx.MultiGraph, tolerance: float = 2.0) -> nx.MultiGraph:
    cleaned = nx.MultiGraph()
    seen_edges: set[tuple] = set()
    removed = 0

    for u, v, key, data in graph.edges(data=True, keys=True):
        geom = data.get("geometry")
        if geom is None:
            cleaned.add_edge(u, v, key=key, **data)
            continue
        centroid = geom.centroid
        quant = (
            round(centroid.x / tolerance) * tolerance,
            round(centroid.y / tolerance) * tolerance,
        )
        f_type = data.get("f_type", "")
        sig = (quant[0], quant[1], f_type)
        if sig in seen_edges:
            removed += 1
            continue
        seen_edges.add(sig)
        cleaned.add_edge(u, v, key=key, **data)

    if removed:
        print(f"  Deduplicated {removed} overlapping boundary edges")
    return cleaned


def merge_graphs(cell_results: list[dict]) -> nx.MultiGraph:
    print("\n\n[5/5] Merging sub-graphs...")
    graphs = []
    for cr in cell_results:
        gpath = cr["graph_path"]
        with open(gpath, "rb") as f:
            g = pickle.load(f)
        graphs.append(g)
        n, e = g.number_of_nodes(), g.number_of_edges()
        print(f"  Loaded {Path(gpath).parent.name}: {n} nodes, {e} edges")

    print(f"  Composing {len(graphs)} graphs...")
    merged = nx.compose_all(graphs)
    print(
        f"  Before dedup: {merged.number_of_nodes()} nodes, "
        f"{merged.number_of_edges()} edges"
    )

    merged = deduplicate_boundary_edges(merged)

    print(
        f"  Final: {merged.number_of_nodes()} nodes, "
        f"{merged.number_of_edges()} edges"
    )

    with open(FINAL_GPICKLE, "wb") as f:
        pickle.dump(merged, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  Saved: {FINAL_GPICKLE}")

    # Write GraphML with WKT geometries
    graphml_graph = nx.MultiGraph()
    for node, ndata in merged.nodes(data=True):
        gdata = dict(ndata)
        if "geometry" in gdata:
            gdata["geometry"] = gdata["geometry"].wkt
        graphml_graph.add_node(node, **gdata)
    for u, v, key, edata in merged.edges(data=True, keys=True):
        gdata = dict(edata)
        if "geometry" in gdata and gdata["geometry"] is not None:
            gdata["geometry"] = gdata["geometry"].wkt
        graphml_graph.add_edge(u, v, key=key, **gdata)

    nx.write_graphml(graphml_graph, str(FINAL_GRAPHML), named_key_ids=True)
    print(f"  Saved: {FINAL_GRAPHML}")

    return merged


# ────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print(f"  Tile2Net — Full Valencia Graph Builder (zoom {ZOOM})")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    ck = load_checkpoint()

    s, w, n, e = get_valencia_bbox()
    lats, lons = build_grid(s, w, n, e, GRID_SIZE)
    register_esri_source()

    ck["bbox"] = [s, n, w, e]
    ck["grid_size"] = GRID_SIZE
    ck["zoom"] = ZOOM
    ck["stitch_step"] = STITCH_STEP
    if "cell_graphs" not in ck:
        ck["cell_graphs"] = {}
    if "completed" not in ck:
        ck["completed"] = []
    save_checkpoint(ck)

    print(f"\n[4/5] Processing {GRID_SIZE * GRID_SIZE} cells...")
    print(f"  Checkpoint: {len(ck.get('cell_graphs', {}))} cells already done")

    results = []
    total = GRID_SIZE * GRID_SIZE

    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            cell_idx = row * GRID_SIZE + col + 1
            cell_name = f"val_g20_r{row}c{col}"
            cell_bbox = [
                float(lats[row]),
                float(lons[col]),
                float(lats[row + 1]),
                float(lons[col + 1]),
            ]

            if is_cell_done(ck, row, col):
                gpath = ck["cell_graphs"].get(f"{row}_{col}", "")
                if gpath and os.path.exists(gpath):
                    results.append(
                        {"row": row, "col": col, "graph_path": gpath}
                    )
                    print(f"  [{row},{col}] Skipped (already done)")
                    continue

            print(f"\n{'─' * 40}")
            print(f"  Cell {cell_idx}/{total}: [{row},{col}] {cell_name}")
            print(f"  Bbox: S={cell_bbox[0]:.5f} W={cell_bbox[1]:.5f} "
                  f"N={cell_bbox[2]:.5f} E={cell_bbox[3]:.5f}")

            try:
                res = process_cell(row, col, cell_bbox, cell_name, ck)
                results.append(res)
            except Exception as exc:
                print(f"\n  *** CELL [{row},{col}] FAILED ***")
                print(f"  Error: {exc}")
                traceback.print_exc()
                # Save checkpoint anyway (in_progress remains so we can retry)
                ck["in_progress"] = None
                save_checkpoint(ck)
                print(f"  Checkpoint saved. Fix the issue and re-run to resume.")
                print(f"  Continuing with remaining cells...")
                continue

    print(f"\n  Completed {len(results)}/{total} cells")

    if not results:
        print("ERROR: No cells completed. Nothing to merge.")
        sys.exit(1)

    merged = merge_graphs(results)

    print("\n" + "=" * 60)
    print(f"  DONE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Nodes: {merged.number_of_nodes():,}")
    print(f"  Edges: {merged.number_of_edges():,}")
    print(f"  Output: {OUTPUT_ROOT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
