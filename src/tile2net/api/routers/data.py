"""Data query endpoints — polygons, network, graph as GeoJSON."""
from __future__ import annotations

import geopandas as gpd
import networkx as nx
from fastapi import APIRouter, HTTPException, Query

from tile2net.api.deps import get_project_db
from tile2net.api.exceptions import ProjectNotFoundError
from tile2net.api.schemas import GraphSummary
from tile2net.api.utils import bbox_from_string, edge_length_sum, gdf_to_geojson
from tile2net.duckdb import read_graph, read_network, read_polygons

router = APIRouter()


def _clip_gdf(gdf: gpd.GeoDataFrame, bbox: tuple | None) -> gpd.GeoDataFrame:
    if bbox and not gdf.empty:
        s, w, n, e = bbox
        gdf_4326 = gdf.to_crs("EPSG:4326")
        gdf_4326 = gdf_4326.cx[w:e, s:n]
        return gdf.loc[gdf_4326.index]
    return gdf


def _parse_bbox(raw: str | None) -> tuple | None:
    if raw is None:
        return None
    parsed = bbox_from_string(raw)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"Invalid bbox format: {raw!r}")
    return parsed


@router.get(
    "/{name}/polygons",
    summary="Query polygons as GeoJSON",
    responses={
        404: {"description": "Project not found"},
        400: {"description": "Invalid bbox format"},
    },
)
def get_polygons(
    name: str,
    f_type: str | None = Query(
        None,
        description="Filter by f_type: ``sidewalk``, ``road``, or ``crosswalk``.",
    ),
    bbox: str | None = Query(
        None,
        description="Clip to bounding box ``S,W,N,E`` in WGS84 decimal degrees.",
    ),
    limit: int = Query(
        10000,
        ge=1,
        le=100000,
        description="Maximum number of features to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Skip the first *offset* features (pagination).",
    ),
):
    """Return cleaned sidewalk/road/crosswalk polygons as a GeoJSON FeatureCollection.

    Polygons are in **WGS84** (EPSG:4326).  Each feature includes ``f_type``,
    ``width`` (metres), and ``source`` properties.
    """
    try:
        con = get_project_db(name)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")

    gdf = read_polygons(con, name)
    con.close()

    if f_type:
        gdf = gdf[gdf["f_type"] == f_type]

    parsed_bbox = _parse_bbox(bbox)
    gdf = _clip_gdf(gdf, parsed_bbox)

    if offset:
        gdf = gdf.iloc[offset:]
    gdf = gdf.iloc[:limit]
    return gdf_to_geojson(gdf)


@router.get(
    "/{name}/network",
    summary="Query network edges as GeoJSON",
    responses={
        404: {"description": "Project not found"},
        400: {"description": "Invalid bbox format"},
    },
)
def get_network(
    name: str,
    f_type: str | None = Query(
        None,
        description="Filter by f_type (e.g. ``sidewalk``, ``crosswalk``).",
    ),
    bbox: str | None = Query(
        None,
        description="Clip to bounding box ``S,W,N,E`` in WGS84 decimal degrees.",
    ),
    min_width: float | None = Query(
        None,
        ge=0,
        description="Only return edges whose width (metres) is >= this value.",
    ),
    limit: int = Query(
        10000,
        ge=1,
        le=100000,
        description="Maximum number of features to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Skip the first *offset* features (pagination).",
    ),
):
    """Return the annotated pedestrian centreline network as GeoJSON.

    Edges are in **WGS84** (EPSG:4326).  Each feature includes ``f_type``,
    ``width`` (metres), ``width_source`` (``spatial`` / ``propagation`` /
    ``median``), ``length`` (metres), and ``source`` properties.
    Every edge is guaranteed to have a non-NaN width.
    """
    try:
        con = get_project_db(name)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")

    gdf = read_network(con, name)
    con.close()

    if f_type:
        gdf = gdf[gdf["f_type"] == f_type]
    if min_width is not None:
        gdf = gdf[gdf["width"] >= min_width]

    parsed_bbox = _parse_bbox(bbox)
    gdf = _clip_gdf(gdf, parsed_bbox)

    if offset:
        gdf = gdf.iloc[offset:]
    gdf = gdf.iloc[:limit]
    return gdf_to_geojson(gdf)


@router.get(
    "/{name}/graph",
    response_model=GraphSummary,
    summary="Get graph summary statistics",
    responses={404: {"description": "Project not found"}},
)
def get_graph_summary(name: str):
    """Return lightweight statistics for the pedestrian graph.

    Includes node count, edge count, total length (metres), and the
    number of connected components.  No geometry is returned.
    """
    try:
        con = get_project_db(name)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")

    try:
        g = read_graph(con, name)
    finally:
        con.close()

    total_length = edge_length_sum(g)
    components = len(list(nx.connected_components(g)))
    return GraphSummary(
        project_name=name,
        node_count=g.number_of_nodes(),
        edge_count=g.number_of_edges(),
        total_length_m=round(total_length, 2),
        crs="EPSG:25830",
        components=components,
    )


@router.get(
    "/{name}/graph/edges",
    summary="Query graph edges as GeoJSON",
    responses={
        404: {"description": "Project not found"},
        400: {"description": "Invalid bbox format"},
    },
)
def get_graph_edges(
    name: str,
    bbox: str | None = Query(
        None,
        description="Clip to bounding box ``S,W,N,E`` in WGS84 decimal degrees.",
    ),
    min_width: float | None = Query(
        None,
        ge=0,
        description="Only return edges whose width (metres) is >= this value.",
    ),
    f_type: str | None = Query(
        None,
        description="Filter by f_type (e.g. ``sidewalk``, ``crosswalk``).",
    ),
    limit: int = Query(
        10000,
        ge=1,
        le=100000,
        description="Maximum number of features to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Skip the first *offset* features (pagination).",
    ),
):
    """Return graph edges from the weighted pedestrian MultiGraph as GeoJSON.

    Each edge includes its ``f_type``, ``width``, ``width_source``
    (``spatial`` / ``propagation`` / ``median``), ``length``, and ``source``.
    MultiGraph edges with the same endpoints but different keys are returned
    as separate features.
    """
    try:
        con = get_project_db(name)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")

    try:
        g = read_graph(con, name)
    finally:
        con.close()

    rows = []
    for u, v, k, data in g.edges(data=True, keys=True):
        geom = data.get("geometry")
        if geom is None:
            continue
        rows.append({
            "geometry": geom,
            "f_type": data.get("f_type", ""),
            "width": data.get("width", None),
            "width_source": data.get("width_source", ""),
            "length": data.get("length", 0),
            "source": data.get("source", ""),
        })

    if not rows:
        return {"type": "FeatureCollection", "features": []}

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:25830")

    if f_type:
        gdf = gdf[gdf["f_type"] == f_type]
    if min_width is not None:
        gdf = gdf[gdf["width"] >= min_width]

    parsed_bbox = _parse_bbox(bbox)
    gdf = _clip_gdf(gdf, parsed_bbox)

    if offset:
        gdf = gdf.iloc[offset:]
    gdf = gdf.iloc[:limit]
    return gdf_to_geojson(gdf)
