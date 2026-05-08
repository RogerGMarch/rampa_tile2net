"""Gap-fill logic: footway centerlines and road-edge sidewalks.

Two passes are performed for every OSM edge in the viario:

Pass 1 — Footway centerlines
    For ways tagged highway ∈ {footway, path, pedestrian, steps, …}, buffer the
    centerline by an estimated half-width and add the uncovered portion as a new
    sidewalk polygon.

Pass 2 — Road-edge sidewalks
    For ways tagged highway ∈ {primary, secondary, …} *and* sidewalk ∈ {left,
    right, both, yes}, create a parallel offset line at the road edge and apply
    the same half-width fill.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

if TYPE_CHECKING:
    from tile2net.postprocess.processor import PostProcessConfig


# OSM highway type sets ---------------------------------------------------------

_FOOT_TYPES = frozenset({
    "footway", "path", "pedestrian", "steps", "living_street", "service",
})

_ROAD_TYPES = frozenset({
    "primary", "secondary", "tertiary", "residential",
    "unclassified", "trunk", "living_street", "service",
})

# Estimated half-width of the *road carriageway* (used to offset the edge line)
_ROAD_CARRIAGEWAY_HW: dict[str, float] = {
    "trunk": 8.0,
    "primary": 7.0,
    "secondary": 6.0,
    "tertiary": 5.0,
    "residential": 4.0,
    "unclassified": 4.0,
    "living_street": 3.0,
    "service": 3.0,
}

# Default fill half-widths when no reference polygon is found nearby
_DEFAULT_FILL_HW: dict[str, float] = {
    "footway": 1.5,
    "pedestrian": 2.5,
    "path": 1.2,
    "steps": 1.0,
    "road_edge": 1.5,
}


# ── internal helpers ───────────────────────────────────────────────────────────

def _polygon_parts(geom: Optional[BaseGeometry]):
    """Yield only Polygon parts from any geometry (handles MultiPolygon, etc.)."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        yield from geom.geoms


def _estimate_hw(
    line: BaseGeometry,
    sw_gdf: gpd.GeoDataFrame,
    sindex: STRtree,
    touch_buf: float,
    fallback_buf: float,
    half_w_clamp: tuple[float, float],
    default_hw: float,
) -> float:
    """Estimate fill half-width from the mean width of touching sidewalk polygons.

    Returns *default_hw* when no polygon is found within *fallback_buf*.
    """
    for radius in (touch_buf, fallback_buf):
        zone = line.buffer(radius)
        cand_idx = list(sindex.intersection(zone.bounds))
        if not cand_idx:
            continue
        cands = sw_gdf.iloc[cand_idx]
        near = cands[cands.geometry.intersects(zone)]
        if near.empty:
            continue
        raw_w = [
            2.0 * g.area / g.exterior.length
            for g in near.geometry
            if g is not None and not g.is_empty and g.exterior.length > 0
        ]
        if raw_w:
            # raw_w values ≈ full polygon width; divide by 2 for half-width
            hw = float(np.mean(raw_w)) / 2.0
            lo, hi = half_w_clamp
            return float(np.clip(hw, lo, hi))
    return default_hw


def _coverage_fraction(candidate: BaseGeometry, poly_union) -> float:
    """Fraction of *candidate* (buffered geometry) already covered by *poly_union*."""
    if candidate.area == 0:
        return 0.0
    covered = candidate.intersection(poly_union)
    return covered.area / candidate.area


def _make_fill_rows(
    poly_union,
    block_mask,
    min_area: float,
    ref_row: dict,
    buf_geom: BaseGeometry,
    hw: float,
    source_label: str = "gap_fill",
) -> list[dict]:
    fill = buf_geom.difference(poly_union)
    if block_mask is not None:
        fill = fill.difference(block_mask)
    rows = []
    for part in _polygon_parts(fill):
        if part.area >= min_area:
            r = dict(ref_row)
            r["geometry"] = part
            r["f_type"] = "sidewalk"
            r["source"] = source_label
            r["width"] = hw * 2.0
            rows.append(r)
    return rows


# ── public API ─────────────────────────────────────────────────────────────────

def fill_gaps(
    viario_gdf_m: gpd.GeoDataFrame,
    sw_gdf_m: gpd.GeoDataFrame,
    poly_union_m: BaseGeometry,
    block_mask,
    config: "PostProcessConfig",
    ref_row: dict,
) -> list[dict]:
    sindex: STRtree = sw_gdf_m.sindex
    fills: list[dict] = []

    # ── Pass 1: footway / path centerlines ────────────────────────────────
    foot_gdf = viario_gdf_m[viario_gdf_m["highway"].isin(_FOOT_TYPES)]
    for _, row in foot_gdf.iterrows():
        line: BaseGeometry = row.geometry
        if line is None or line.is_empty:
            continue

        hw = _estimate_hw(
            line, sw_gdf_m, sindex,
            config.touch_buf, config.fallback_buf, config.half_w_clamp,
            _DEFAULT_FILL_HW.get(str(row.get("highway", "")), 1.5),
        )
        buf_geom = line.buffer(hw)

        if _coverage_fraction(buf_geom, poly_union_m) >= config.fill_cov_max:
            continue

        fills.extend(
            _make_fill_rows(poly_union_m, block_mask, config.min_area, ref_row, buf_geom, hw)
        )

    # ── Pass 2: road-edge sidewalks ───────────────────────────────────────
    road_mask = (
        viario_gdf_m["highway"].isin(_ROAD_TYPES)
        & viario_gdf_m["sidewalk"].isin({"left", "right", "both", "yes"})
    )
    road_gdf = viario_gdf_m[road_mask]
    for _, row in road_gdf.iterrows():
        line: BaseGeometry = row.geometry
        if line is None or line.is_empty:
            continue
        road_hw = _ROAD_CARRIAGEWAY_HW.get(str(row.get("highway", "")), 4.0)
        sw_tag = str(row.get("sidewalk", ""))
        sides = ["left", "right"] if sw_tag in ("both", "yes") else [sw_tag]

        for side in sides:
            try:
                edge_line = line.parallel_offset(road_hw, side)
            except Exception:
                continue
            if edge_line is None or edge_line.is_empty:
                continue

            hw = _estimate_hw(
                edge_line, sw_gdf_m, sindex,
                config.touch_buf, config.fallback_buf, config.half_w_clamp,
                _DEFAULT_FILL_HW["road_edge"],
            )
            buf_geom = edge_line.buffer(hw)

            if _coverage_fraction(buf_geom, poly_union_m) >= config.fill_cov_max:
                continue

            fills.extend(
                _make_fill_rows(poly_union_m, block_mask, config.min_area, ref_row, buf_geom, hw)
            )

    return fills
