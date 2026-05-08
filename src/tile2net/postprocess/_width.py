"""Polygon-width estimation helpers."""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree


def polygon_width(geom: Optional[BaseGeometry]) -> float:
    if geom is None or geom.is_empty:
        return float("nan")
    try:
        exterior = geom.exterior
    except AttributeError:
        return float("nan")
    if exterior.length == 0:
        return float("nan")
    return 2.0 * geom.area / exterior.length


def estimate_edge_width(
    edge_geom: BaseGeometry,
    poly_gdf: gpd.GeoDataFrame,
    sindex: STRtree,
    touch_buf: float,
    fallback_buf: float,
    half_w_clamp: tuple[float, float],
    default: float = float("nan"),
) -> float:
    lo, hi = half_w_clamp
    for radius in (touch_buf, fallback_buf):
        zone = edge_geom.buffer(radius)
        cand_idx = list(sindex.intersection(zone.bounds))
        if not cand_idx:
            continue
        cands = poly_gdf.iloc[cand_idx]
        nearby = cands[cands.geometry.intersects(zone)]
        if nearby.empty:
            continue
        widths = [
            polygon_width(g)
            for g in nearby.geometry
            if g is not None and not g.is_empty
        ]
        widths = [w for w in widths if not np.isnan(w)]
        if widths:
            w_mean = float(np.mean(widths))
            return float(np.clip(w_mean, lo * 2.0, hi * 2.0))
    return default
