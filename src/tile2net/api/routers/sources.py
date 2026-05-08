"""Tile source catalogue — register custom tile sources for tile2net generate."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from tile2net.api.deps import (
    create_source as _create_source,
    delete_source as _delete_source,
    get_registry_db,
    list_sources as _list_sources,
    read_source as _read_source,
    register_source_runtime,
)
from tile2net.api.schemas import SourceCreate, SourceInfo, SourceList

router = APIRouter()


@router.post(
    "/",
    status_code=201,
    response_model=SourceInfo,
    summary="Register a custom tile source",
    responses={
        409: {"description": "A source with this name already exists"},
        400: {"description": "Invalid bbox or tile URL"},
    },
)
def create_source_endpoint(data: SourceCreate):
    """Register a custom tile source for use by ``tile2net generate -s <name>``.

    The ``tile_url`` must contain ``{z}``, ``{x}``, ``{y}`` placeholders.
    After registration, projects can reference this source via the ``source``
    field in ``ProjectCreate``.
    """
    con = get_registry_db()
    try:
        existing = _read_source(con, data.name)
        if existing:
            raise HTTPException(status_code=409, detail=f"Source {data.name!r} already exists")

        row = {
            "name": data.name,
            "tile_url": data.tile_url,
            "bbox_s": data.bbox_s,
            "bbox_w": data.bbox_w,
            "bbox_n": data.bbox_n,
            "bbox_e": data.bbox_e,
            "zoom_max": data.zoom_max,
            "server": data.server,
            "extension": data.extension,
            "tilesize": data.tilesize,
            "keyword": data.keyword or data.name,
        }
        _create_source(con, row)
        return SourceInfo(**row)
    finally:
        con.close()


@router.get(
    "/",
    response_model=SourceList,
    summary="List all registered tile sources",
)
def list_sources_endpoint():
    """Return all custom tile sources registered in the catalogue."""
    con = get_registry_db()
    try:
        rows = _list_sources(con)
        return SourceList(sources=[SourceInfo(**r) for r in rows])
    finally:
        con.close()


@router.get(
    "/{name}",
    response_model=SourceInfo,
    summary="Get a single tile source",
    responses={404: {"description": "Source not found"}},
)
def get_source_endpoint(name: str):
    """Return the full configuration of a registered tile source."""
    con = get_registry_db()
    try:
        row = _read_source(con, name)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Source {name!r} not found")
        return SourceInfo(**row)
    finally:
        con.close()


@router.delete(
    "/{name}",
    summary="Delete a tile source",
    responses={404: {"description": "Source not found"}},
)
def delete_source_endpoint(name: str):
    """Remove a custom tile source from the catalogue."""
    con = get_registry_db()
    try:
        deleted = _delete_source(con, name)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Source {name!r} not found")
        return {"name": name, "deleted": True}
    finally:
        con.close()
