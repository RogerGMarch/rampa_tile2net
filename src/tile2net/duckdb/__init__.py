"""DuckDB storage layer for tile2net outputs.

Provides connection management and read/write helpers for:
- orthophoto tiles (PNG blobs)
- post-process polygons and network edges (GeoDataFrame round-trip)
- weighted pedestrian MultiGraph (NetworkX round-trip)
"""
from tile2net.duckdb.connection import get_duckdb_connection, get_project_db
from tile2net.duckdb.db_models import (
    list_tiles,
    read_graph,
    read_network,
    read_polygons,
    read_tile,
    write_graph,
    write_network,
    write_polygons,
    write_tiles,
)

__all__ = [
    "get_duckdb_connection",
    "get_project_db",
    "write_tiles",
    "read_tile",
    "list_tiles",
    "write_polygons",
    "read_polygons",
    "write_network",
    "read_network",
    "write_graph",
    "read_graph",
]
