"""DuckDB connection helpers with spatial + json extensions loaded."""
from __future__ import annotations

from pathlib import Path

import duckdb


def get_duckdb_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with spatial + json extensions loaded.

    Args:
        db_path: Path to a ``.db`` file or directory.  Creates parent
            directories if needed.  Pass ``None`` (default) for an in-memory
            database.

    Returns:
        Connection ready for geospatial queries.
    """
    if db_path:
        path = Path(db_path)
        if not path.name.endswith(".db"):
            path = path / "tile2net.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path))
    else:
        con = duckdb.connect(":memory:")

    # load geospatial + json extensions
    for ext in ("spatial", "json"):
        try:
            con.install_extension(ext)
            con.load_extension(ext)
        except Exception:
            pass

    return con


def get_project_db(project_dir: str | Path) -> duckdb.DuckDBPyConnection:
    """Convenience: open the DuckDB for a tile2net project directory.

    Opens ``{project_dir}/tile2net.db`` and loads spatial extensions.
    """
    return get_duckdb_connection(Path(project_dir) / "tile2net.db")
