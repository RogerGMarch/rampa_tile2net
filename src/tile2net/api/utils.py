"""Shared utilities — geocoding, GeoJSON conversion, bbox parsing."""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import networkx as nx


def bbox_from_string(s: str) -> tuple[float, float, float, float] | None:
    """Parse ``S,W,N,E`` or ``W,S,E,N`` string to (S, W, N, E) tuple."""
    parts = s.replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    a, b, c, d = nums
    # Heuristic: if first two are > 90 it's lat,lng format (S,W,N,E)
    if abs(a) <= 90 and abs(b) <= 180 and abs(c) <= 90 and abs(d) <= 180:
        if a < -90 or a > 90 or c < -90 or c > 90:
            return None
        return (a, b, c, d)  # S, W, N, E
    return None


def bbox_from_location(location: str) -> tuple[float, float, float, float]:
    """Return ``(S, W, N, E)`` bbox from a location string.

    If *location* is ``S,W,N,E``, parse directly.  Otherwise geocode
    via :func:`osmnx.geocode` and return the bounding box.
    """
    parsed = bbox_from_string(location)
    if parsed is not None:
        return parsed
    try:
        import osmnx as ox
        gdf = ox.geocode_to_gdf(location)
    except Exception:
        raise ValueError(
            f"Could not geocode location: {location!r}. "
            "Provide a bbox as 'S,W,N,E' or a valid nominatim query."
        )
    if gdf.empty:
        raise ValueError(f"Could not geocode location: {location!r}")
    w, s, e, n = gdf.total_bounds
    return (float(s), float(w), float(n), float(e))


def gdf_to_geojson(gdf: gpd.GeoDataFrame, dst_crs: str = "EPSG:4326") -> dict:
    """Convert a GeoDataFrame to a GeoJSON FeatureCollection dict.

    Reprojects to *dst_crs*, drops non-geometry metadata columns, and
    returns the ``__geo_interface__`` dict.
    """
    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    gdf = gdf.to_crs(dst_crs)
    # keep only geometry + meaningful attribute columns
    keep = ["geometry", "f_type", "width", "width_source", "length", "source"]
    cols = [c for c in keep if c in gdf.columns]
    result = gdf[cols].__geo_interface__
    # remove 'id' key that gpd inserts
    for feat in result.get("features", []):
        feat.pop("id", None)
    return result


def edge_length_sum(graph: nx.MultiGraph) -> float:
    """Sum of all edge ``length`` attributes, falling back to ``geometry.length``."""
    total = 0.0
    for _u, _v, _k, data in graph.edges(data=True, keys=True):
        length = data.get("length")
        if length is not None and length > 0:
            total += float(length)
        elif (geom := data.get("geometry")) is not None:
            total += geom.length
    return total
