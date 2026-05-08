"""FastAPI dependency injection — DuckDB connections + registry CRUD."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb

from tile2net.api.config import get_api_config
from tile2net.api.exceptions import ProjectNotFoundError
from tile2net.duckdb import get_duckdb_connection as _open_db


# ── Registry helpers ───────────────────────────────────────────────────────────

def _ensure_registry(con) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS projects ("
        "  name VARCHAR PRIMARY KEY,"
        "  location VARCHAR NOT NULL,"
        "  zoom INTEGER NOT NULL DEFAULT 19,"
        "  crs INTEGER NOT NULL DEFAULT 4326,"
        "  metric_crs VARCHAR NOT NULL DEFAULT 'EPSG:25830',"
        "  source VARCHAR,"
        "  tile_step INTEGER DEFAULT 1,"
        "  stitch_step INTEGER DEFAULT 4,"
        "  viario_type VARCHAR DEFAULT 'osm',"
        "  viario_url VARCHAR,"
        "  output_dir VARCHAR NOT NULL,"
        "  bbox_s DOUBLE, bbox_w DOUBLE, bbox_n DOUBLE, bbox_e DOUBLE,"
        "  status VARCHAR NOT NULL DEFAULT 'created',"
        "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )


def get_registry_db() -> duckdb.DuckDBPyConnection:
    cfg = get_api_config()
    cfg.registry_path.parent.mkdir(parents=True, exist_ok=True)
    con = _open_db(cfg.registry_path)
    _ensure_registry(con)
    return con


def get_project_db(project_name: str) -> duckdb.DuckDBPyConnection:
    cfg = get_api_config()
    con = get_registry_db()
    row = con.execute(
        "SELECT output_dir FROM projects WHERE name=?", [project_name]
    ).fetchone()
    con.close()
    if row is None:
        raise ProjectNotFoundError(f"Project not found: {project_name!r}")
    output_dir = Path(row[0])
    return _open_db(output_dir / "tile2net.db")


# ── Registry CRUD ──────────────────────────────────────────────────────────────

def create_project(con, data: dict) -> str:
    _ensure_registry(con)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO projects (name, location, zoom, crs, metric_crs, source, "
        "tile_step, stitch_step, viario_type, viario_url, output_dir, status, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            data["name"], data["location"], data["zoom"], data["crs"],
            data["metric_crs"], data.get("source"),
            data.get("tile_step", 1), data.get("stitch_step", 4),
            data.get("viario_type", "osm"), data.get("viario_url"),
            data["output_dir"], "created", now, now,
        ],
    )
    return data["name"]


def read_project(con, name: str) -> dict | None:
    _ensure_registry(con)
    row = con.execute(
        "SELECT * FROM projects WHERE name=?", [name]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row))


def list_projects(con, status: str | None = None) -> list[dict]:
    _ensure_registry(con)
    if status:
        rows = con.execute(
            "SELECT * FROM projects WHERE status=? ORDER BY created_at DESC",
            [status],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


def update_project_status(
    con, name: str, status: str, bbox: tuple | None = None
) -> None:
    _ensure_registry(con)
    now = datetime.now(timezone.utc).isoformat()
    if bbox:
        con.execute(
            "UPDATE projects SET status=?, bbox_s=?, bbox_w=?, bbox_n=?, bbox_e=?, "
            "updated_at=? WHERE name=?",
            [status, bbox[0], bbox[1], bbox[2], bbox[3], now, name],
        )
    else:
        con.execute(
            "UPDATE projects SET status=?, updated_at=? WHERE name=?",
            [status, now, name],
        )


def update_project_fields(con, name: str, **kwargs) -> bool:
    _ensure_registry(con)
    row = con.execute("SELECT name FROM projects WHERE name=?", [name]).fetchone()
    if row is None:
        return False
    now = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    con.execute(
        f"UPDATE projects SET {sets}, updated_at=? WHERE name=?",
        [*kwargs.values(), now, name],
    )
    return True


def delete_project(con, name: str) -> bool:
    _ensure_registry(con)
    row = con.execute("SELECT name FROM projects WHERE name=?", [name]).fetchone()
    if row is None:
        return False
    con.execute("DELETE FROM projects WHERE name=?", [name])
    return True


# ── Source catalogue ───────────────────────────────────────────────────────────

def _ensure_sources_table(con) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS sources ("
        "  name VARCHAR PRIMARY KEY,"
        "  tile_url VARCHAR NOT NULL,"
        "  bbox_s DOUBLE, bbox_w DOUBLE, bbox_n DOUBLE, bbox_e DOUBLE,"
        "  zoom_max INTEGER NOT NULL DEFAULT 20,"
        "  server VARCHAR,"
        "  extension VARCHAR DEFAULT 'png',"
        "  tilesize INTEGER DEFAULT 256,"
        "  keyword VARCHAR"
        ")"
    )


def create_source(con, data: dict) -> str:
    _ensure_sources_table(con)
    con.execute(
        "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            data["name"], data["tile_url"],
            data["bbox_s"], data["bbox_w"], data["bbox_n"], data["bbox_e"],
            data.get("zoom_max", 20), data.get("server"),
            data.get("extension", "png"), data.get("tilesize", 256),
            data.get("keyword"),
        ],
    )
    return data["name"]


def read_source(con, name: str) -> dict | None:
    _ensure_sources_table(con)
    row = con.execute("SELECT * FROM sources WHERE name=?", [name]).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row))


def list_sources(con) -> list[dict]:
    _ensure_sources_table(con)
    rows = con.execute("SELECT * FROM sources ORDER BY name").fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


def delete_source(con, name: str) -> bool:
    _ensure_sources_table(con)
    row = con.execute("SELECT name FROM sources WHERE name=?", [name]).fetchone()
    if row is None:
        return False
    con.execute("DELETE FROM sources WHERE name=?", [name])
    return True


def register_source_runtime(source_row: dict) -> None:
    """Dynamically register a source in the tile2net ``SourceMeta.catalog``.

    Creates a synthetic ``Source`` subclass so that ``Source[name]`` returns it.
    """
    from geopandas import GeoSeries
    from shapely.geometry import box

    from tile2net.raster.source import Source, SourceMeta

    name = source_row["name"]
    if name in SourceMeta.catalog:
        return

    tile_url = source_row["tile_url"]

    ns = {
        "name": name,
        "keyword": source_row.get("keyword") or name,
        "zoom": source_row.get("zoom_max", 20),
        "extension": source_row.get("extension", "png"),
        "tilesize": source_row.get("tilesize", 256),
        "server": source_row.get("server", ""),
    }
    cls = type(name, (Source,), ns)

    cls.coverage = GeoSeries(
        [box(
            source_row["bbox_w"], source_row["bbox_s"],
            source_row["bbox_e"], source_row["bbox_n"],
        )],
        crs="EPSG:4326",
    )

    # Assign tile_url via class-level property so self.tiles returns it
    cls.tiles = property(lambda self, u=tile_url: u)

    SourceMeta.catalog[name] = cls
