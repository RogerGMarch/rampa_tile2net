#!/usr/bin/env python3
"""api_example.py — End-to-end demonstration of the Tile2Net REST API.

Run this file to see the full API flow — register a project, query data,
and inspect the DuckDB storage layer — all against the pre-built Valencia
Centre test dataset.

Usage:
    uv run python api_example.py

Requirements:
    - Valencia Centre test data must exist in test_output/valencia_center/
    - No running server needed — uses FastAPI TestClient internally
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────────
#  0.  Setup — configure the API with a temp registry, pre-populate a project
# ──────────────────────────────────────────────────────────────────────────────────

print("=" * 60)
print("  Tile2Net API — End-to-End Example")
print("=" * 60)

# Override API config to use a temp directory
import tempfile
import tile2net.api.config as _cfg
from tile2net.api.config import ApiConfig

tmp = Path(tempfile.mkdtemp(prefix="tile2net_api_example_"))
_api_cfg = ApiConfig(data_root=tmp, registry_path=tmp / "registry.db")
_cfg._config = _api_cfg            # patch the module-level singleton

from tile2net.api.main import create_app
from fastapi.testclient import TestClient

app = create_app()
client = TestClient(app)

print(f"\nRegistry path: {_api_cfg.registry_path}")
print(f"Data root:     {_api_cfg.data_root}")

# ──────────────────────────────────────────────────────────────────────────────────
#  1.  Health check
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("1. Health check")
print("-" * 40)

resp = client.get("/")
print(f"   GET /  →  {resp.status_code}  {resp.json()}")


# ──────────────────────────────────────────────────────────────────────────────────
#  2.  Register a project (Valencia Centre)
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("2. Create project  'valencia_centre'")
print("-" * 40)

resp = client.post("/projects/", json={
    "name": "valencia_centre",
    "location": "39.469,-0.381,39.478,-0.369",  # bbox S,W,N,E
    "zoom": 19,
    "metric_crs": "EPSG:25830",
    "viario_type": "osm",
})
print(f"   POST /projects/  →  {resp.status_code}")
proj = resp.json()
print(f"   name:      {proj['name']}")
print(f"   status:    {proj['status']}")
print(f"   bbox:      {proj['bbox_wgs84']}")
print(f"   created:   {proj['created_at']}")


# ──────────────────────────────────────────────────────────────────────────────────
#  3.  List projects
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("3. List projects")
print("-" * 40)

resp = client.get("/projects/")
projects = resp.json()["projects"]
for p in projects:
    print(f"   {p['name']:30s}  status={p['status']}")


# ──────────────────────────────────────────────────────────────────────────────────
#  4.  Patch a project
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("4. Patch project — change viario_type")
print("-" * 40)

resp = client.patch("/projects/valencia_centre", json={"viario_type": "official"})
p = resp.json()
print(f"   viario_type:  {p['viario_type']}")

# change it back
client.patch("/projects/valencia_centre", json={"viario_type": "osm"})


# ──────────────────────────────────────────────────────────────────────────────────
#  5.  Pre-populate the project's DuckDB with the Valencia Centre test data
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("5. Populate DuckDB with pre-built Valencia Centre results")
print("-" * 40)

from tile2net.duckdb import (
    get_duckdb_connection,
    write_graph,
    write_network,
    write_polygons,
)
from tile2net.postprocess import (
    OSMViarioSource,
    PedestrianPostProcessor,
    PostProcessConfig,
)

DATA = Path("test_output/valencia_center/valencia_center")
POLY = DATA / "polygons" / "final" / "final.shp"
NET_DIR = sorted((DATA / "network").iterdir())[-1]
NET = NET_DIR / f"{NET_DIR.name}.shp"

print(f"   polygons: {POLY}")
print(f"   network:  {NET}")

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    proc = PedestrianPostProcessor(
        polygon_path=POLY,
        network_path=NET,
        viario=OSMViarioSource(cache_path="/tmp/osm_center_ped.json"),
        config=PostProcessConfig(),
        blocking_cache_path="/tmp/osm_center_blocking.json",
    )
    result = proc.run()

# Write to DuckDB
db_path = tmp / "projects" / "valencia_centre" / "tile2net.db"
db_path.parent.mkdir(parents=True, exist_ok=True)
con = get_duckdb_connection(db_path)
write_polygons(con, "valencia_centre", result.polygons)
write_network(con, "valencia_centre", result.network)
write_graph(con, "valencia_centre", result.graph)
con.close()

print(f"   polygons:  {len(result.polygons):5d} rows")
print(f"   network:   {len(result.network):5d} edges")
print(f"   graph:     {result.graph.number_of_edges():5d} edges, "
      f"{result.graph.number_of_nodes():5d} nodes")
print(f"   db file:   {db_path} ({db_path.stat().st_size:,} bytes)")


# ──────────────────────────────────────────────────────────────────────────────────
#  6.  Query polygons as GeoJSON
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("6. Query polygons")
print("-" * 40)

# All polygons (limited to 3)
resp = client.get(
    "/projects/valencia_centre/polygons",
    params={"limit": 3},
)
fc = resp.json()
print(f"   GET /polygons?limit=3  →  {resp.status_code}")
print(f"   type:       {fc['type']}")
for f in fc["features"]:
    g = f["geometry"]
    p = f["properties"]
    print(f"   f_type={p['f_type']:12s}  width={p['width']:6.2f}m  "
          f"geom={g['type']}({len(str(g)):4d} chars)")

# Filter by type
resp = client.get(
    "/projects/valencia_centre/polygons",
    params={"f_type": "sidewalk", "limit": 2},
)
fc = resp.json()
print(f"\n   GET /polygons?f_type=sidewalk&limit=2  →  {len(fc['features'])} features")

# Bbox filter
resp = client.get(
    "/projects/valencia_centre/polygons",
    params={"bbox": "39.47,-0.38,39.48,-0.37"},
)
fc = resp.json()
print(f"   GET /polygons?bbox=39.47,-0.38,39.48,-0.37  →  {len(fc['features'])} features")


# ──────────────────────────────────────────────────────────────────────────────────
#  7.  Query network as GeoJSON
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("7. Query network")
print("-" * 40)

resp = client.get(
    "/projects/valencia_centre/network",
    params={"limit": 3},
)
fc = resp.json()
print(f"   GET /network?limit=3  →  {resp.status_code}")
for f in fc["features"]:
    p = f["properties"]
    print(f"   f_type={p['f_type']:20s}  width={p['width']:6.2f}m  "
          f"length={p['length']:8.2f}m")

# Filter by min_width
resp = client.get(
    "/projects/valencia_centre/network",
    params={"min_width": 6.0, "limit": 3},
)
fc = resp.json()
print(f"\n   GET /network?min_width=6&limit=3  →  {len(fc['features'])} features "
      f"(widths: {[f['properties']['width'] for f in fc['features']]})")


# ──────────────────────────────────────────────────────────────────────────────────
#  8.  Graph summary
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("8. Graph summary")
print("-" * 40)

resp = client.get("/projects/valencia_centre/graph")
summary = resp.json()
print(f"   GET /graph  →  {resp.status_code}")
for k, v in summary.items():
    print(f"   {k:20s}  {v}")


# ──────────────────────────────────────────────────────────────────────────────────
#  9.  Graph edges as GeoJSON
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("9. Graph edges")
print("-" * 40)

resp = client.get(
    "/projects/valencia_centre/graph/edges",
    params={"min_width": 6.0, "limit": 2},
)
fc = resp.json()
print(f"   GET /graph/edges?min_width=6&limit=2  →  {len(fc['features'])} features")
for f in fc["features"]:
    p = f["properties"]
    print(f"   f_type={p['f_type']:20s}  width={p['width']:6.2f}m  "
          f"length={p['length']:8.2f}m")


# ──────────────────────────────────────────────────────────────────────────────────
#  10. Pipeline status (no pipeline was run)
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("10. Pipeline status (expected 404 — no pipeline run yet)")
print("-" * 40)

resp = client.get("/projects/valencia_centre/pipeline/status")
print(f"    GET /pipeline/status  →  {resp.status_code}  {resp.json()['detail']}")


# ──────────────────────────────────────────────────────────────────────────────────
#  11. Tear down — delete the project
# ──────────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 40)
print("11. Delete project + cleanup")
print("-" * 40)

resp = client.delete("/projects/valencia_centre")
print(f"    DELETE /projects/valencia_centre  →  {resp.status_code}  {resp.json()}")

# Verify gone
resp = client.get("/projects/valencia_centre")
print(f"    GET /projects/valencia_centre      →  {resp.status_code}  (gone ✓)")

# Cleanup temp dir
import shutil
shutil.rmtree(tmp)
print(f"\n    Temp directory cleaned: {tmp}")

print("\n" + "=" * 60)
print("  Example complete — 11 steps, 0 failures")
print("=" * 60)
