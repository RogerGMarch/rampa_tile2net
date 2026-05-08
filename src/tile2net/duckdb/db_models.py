"""DuckDB table DDL and read/write helpers for tile2net outputs."""
from __future__ import annotations

import ast
import warnings
from typing import Optional

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely import wkb
from shapely.geometry import Point

from tile2net.duckdb.connection import get_duckdb_connection


# ── DDL helpers ────────────────────────────────────────────────────────────────

def _ensure_tables(con) -> None:
    """Create all DuckDB tables if they don't exist (GEOMETRY type requires spatial ext)."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS tiles ("
        "  project_name VARCHAR, tx INTEGER, ty INTEGER, zoom INTEGER,"
        "  image BLOB,"
        "  PRIMARY KEY (project_name, tx, ty, zoom)"
        ")"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS polygons ("
        "  project_name VARCHAR, row_id INTEGER,"
        "  f_type VARCHAR, width DOUBLE, source VARCHAR,"
        "  geom GEOMETRY,"
        "  PRIMARY KEY (project_name, row_id)"
        ")"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS network ("
        "  project_name VARCHAR, row_id INTEGER,"
        "  f_type VARCHAR, width DOUBLE, length DOUBLE, source VARCHAR,"
        "  geom GEOMETRY,"
        "  PRIMARY KEY (project_name, row_id)"
        ")"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS graph_nodes ("
        "  project_name VARCHAR, node_id VARCHAR,"
        "  x DOUBLE, y DOUBLE,"
        "  geom GEOMETRY,"
        "  PRIMARY KEY (project_name, node_id)"
        ")"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS graph_edges ("
        "  project_name VARCHAR,"
        "  from_node VARCHAR, to_node VARCHAR, edge_key INTEGER,"
        "  f_type VARCHAR, width DOUBLE, length DOUBLE, source VARCHAR,"
        "  geom GEOMETRY,"
        "  PRIMARY KEY (project_name, from_node, to_node, edge_key)"
        ")"
    )


# ── Tiles ──────────────────────────────────────────────────────────────────────

def write_tiles(
    con,
    project_name: str,
    tiles: dict[tuple[int, int], bytes],
    zoom: int = 19,
) -> None:
    """Insert orthophoto tile PNGs into the *tiles* table.

    Args:
        con: DuckDB connection.
        project_name: Project identifier string.
        tiles: Mapping ``(tx, ty) → PNG bytes``.
        zoom: Slippy-map zoom level (default 19).
    """
    _ensure_tables(con)
    rows = [
        (project_name, tx, ty, zoom, img)
        for (tx, ty), img in tiles.items()
    ]
    con.executemany(
        "INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?, ?)", rows
    )


def read_tile(con, project_name: str, tx: int, ty: int, zoom: int = 19) -> Optional[bytes]:
    """Return the PNG bytes for a single tile, or None."""
    _ensure_tables(con)
    row = con.execute(
        "SELECT image FROM tiles "
        "WHERE project_name=? AND tx=? AND ty=? AND zoom=?",
        [project_name, tx, ty, zoom],
    ).fetchone()
    return row[0] if row else None


def list_tiles(con, project_name: str, zoom: int = 19) -> list[tuple[int, int]]:
    """Return list of ``(tx, ty)`` coordinate pairs stored for the project."""
    _ensure_tables(con)
    rows = con.execute(
        "SELECT tx, ty FROM tiles WHERE project_name=? AND zoom=?",
        [project_name, zoom],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


# ── Polygons ───────────────────────────────────────────────────────────────────

def write_polygons(con, project_name: str, gdf: gpd.GeoDataFrame) -> None:
    """Store cleaned polygons (columns: f_type, width, source, geometry)."""
    _ensure_tables(con)

    gdf = gdf.to_crs("EPSG:4326")
    for col in ("f_type", "width", "source"):
        if col not in gdf.columns:
            gdf[col] = ""

    con.execute("DELETE FROM polygons WHERE project_name=?", [project_name])

    rows = [
        (
            project_name, i,
            str(row.get("f_type", "")),
            float(row.get("width", float("nan"))),
            str(row.get("source", "")),
            row.geometry.wkb,
        )
        for i, row in gdf.iterrows()
    ]
    con.executemany(
        "INSERT INTO polygons VALUES (?, ?, ?, ?, ?, ST_GeomFromWKB(?))", rows
    )


def read_polygons(con, project_name: str) -> gpd.GeoDataFrame:
    """Return all cleaned polygons for a project as a GeoDataFrame."""
    _ensure_tables(con)
    df = con.execute(
        "SELECT row_id, f_type, width, source, ST_AsBinary(geom) AS geom_wkb "
        "FROM polygons WHERE project_name=? ORDER BY row_id",
        [project_name],
    ).fetchdf()
    if df.empty:
        return gpd.GeoDataFrame(
            columns=["f_type", "width", "source", "geometry"],
            geometry="geometry",
        )
    df["geometry"] = df["geom_wkb"].apply(lambda b: wkb.loads(bytes(b)))
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    gdf.drop(columns=["geom_wkb", "row_id"], inplace=True)
    return gdf


# ── Network ────────────────────────────────────────────────────────────────────

def write_network(con, project_name: str, gdf: gpd.GeoDataFrame) -> None:
    """Store annotated network edges (columns: f_type, width, length, source, geometry)."""
    _ensure_tables(con)

    gdf = gdf.to_crs("EPSG:4326")
    for col in ("f_type", "width", "length", "source"):
        if col not in gdf.columns:
            gdf[col] = "" if col == "source" else float("nan")

    con.execute("DELETE FROM network WHERE project_name=?", [project_name])

    rows = [
        (
            project_name, i,
            str(row.get("f_type", "")),
            float(row.get("width", float("nan"))),
            float(row.get("length", 0.0)),
            str(row.get("source", "")),
            row.geometry.wkb,
        )
        for i, row in gdf.iterrows()
    ]
    con.executemany(
        "INSERT INTO network VALUES (?, ?, ?, ?, ?, ?, ST_GeomFromWKB(?))", rows
    )


def read_network(con, project_name: str) -> gpd.GeoDataFrame:
    """Return all annotated network edges as a GeoDataFrame."""
    _ensure_tables(con)
    df = con.execute(
        "SELECT row_id, f_type, width, length, source, ST_AsBinary(geom) AS geom_wkb "
        "FROM network WHERE project_name=? ORDER BY row_id",
        [project_name],
    ).fetchdf()
    if df.empty:
        return gpd.GeoDataFrame(
            columns=["f_type", "width", "length", "source", "geometry"],
            geometry="geometry",
        )
    df["geometry"] = df["geom_wkb"].apply(lambda b: wkb.loads(bytes(b)))
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    gdf.drop(columns=["geom_wkb", "row_id"], inplace=True)
    return gdf


# ── Graph ──────────────────────────────────────────────────────────────────────

def _node_id(x: float, y: float) -> str:
    """Consistent string representation for a node coordinate tuple."""
    return str((round(x, 6), round(y, 6)))


def _parse_node_id(s: str) -> tuple[float, float]:
    """Reverse :func:`_node_id` back to ``(x, y)``."""
    return ast.literal_eval(s)


def write_graph(con, project_name: str, graph: nx.MultiGraph) -> None:
    """Persist a NetworkX MultiGraph as *graph_nodes* + *graph_edges* tables.

    Geometry and coordinates are stored in their original metric CRS.
    """
    _ensure_tables(con)

    con.execute("DELETE FROM graph_edges WHERE project_name=?", [project_name])
    con.execute("DELETE FROM graph_nodes WHERE project_name=?", [project_name])

    # nodes
    node_rows = []
    for node, data in graph.nodes(data=True):
        mx = data.get("x", 0)
        my = data.get("y", 0)
        nid = _node_id(mx, my)
        pt = Point(mx, my)
        node_rows.append((project_name, nid, mx, my, pt.wkb))
    con.executemany(
        "INSERT INTO graph_nodes VALUES (?, ?, ?, ?, ST_GeomFromWKB(?))", node_rows
    )

    # edges
    edge_rows = []
    for u, v, k, data in graph.edges(data=True, keys=True):
        u_x, u_y = graph.nodes[u].get("x", 0), graph.nodes[u].get("y", 0)
        v_x, v_y = graph.nodes[v].get("x", 0), graph.nodes[v].get("y", 0)
        u_nid = _node_id(u_x, u_y)
        v_nid = _node_id(v_x, v_y)
        geom = data.get("geometry")
        wkb_bytes = geom.wkb if geom is not None else Point().wkb
        edge_rows.append((
            project_name,
            u_nid, v_nid, int(k),
            str(data.get("f_type", "")),
            float(data.get("width", float("nan"))),
            float(data.get("length", 0.0)),
            str(data.get("source", "")),
            wkb_bytes,
        ))
    con.executemany(
        "INSERT INTO graph_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ST_GeomFromWKB(?))",
        edge_rows,
    )


def read_graph(con, project_name: str) -> nx.MultiGraph:
    """Reconstruct a NetworkX MultiGraph from DuckDB tables."""
    _ensure_tables(con)
    G = nx.MultiGraph()

    # nodes
    node_df = con.execute(
        "SELECT node_id, x, y, ST_AsBinary(geom) AS geom_wkb "
        "FROM graph_nodes WHERE project_name=?",
        [project_name],
    ).fetchdf()
    for _, row in node_df.iterrows():
        x, y = row["x"], row["y"]
        geom_blob = row["geom_wkb"]
        G.add_node(
            row["node_id"],
            x=x, y=y,
            geometry=wkb.loads(bytes(geom_blob)) if geom_blob else Point(x, y),
        )

    # edges
    edge_df = con.execute(
        "SELECT from_node, to_node, edge_key, f_type, width, length, source, "
        "ST_AsBinary(geom) AS geom_wkb "
        "FROM graph_edges WHERE project_name=? ORDER BY from_node, to_node, edge_key",
        [project_name],
    ).fetchdf()
    for _, row in edge_df.iterrows():
        geom_blob = row["geom_wkb"]
        G.add_edge(
            row["from_node"], row["to_node"], key=int(row["edge_key"]),
            f_type=row.get("f_type", ""),
            width=row.get("width", float("nan")),
            length=row.get("length", 0.0),
            source=row.get("source", ""),
            geometry=wkb.loads(bytes(geom_blob)) if geom_blob else None,
        )

    return G
