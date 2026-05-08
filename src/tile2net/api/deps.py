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
