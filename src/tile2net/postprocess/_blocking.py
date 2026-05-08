"""Fetch OSM blocking polygons (buildings + leisure areas) for subtraction."""
from __future__ import annotations

import json
import time
import urllib.request
import warnings
from pathlib import Path
from typing import Optional

import geopandas as gpd
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_MAX_RETRIES = 3


def _overpass_fetch(query: str, cache_path: Optional[Path] = None) -> dict:
    if cache_path is not None and cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    for attempt in range(_MAX_RETRIES):
        try:
            data_bytes = urllib.request.urlopen(
                _OVERPASS_URL, data=query.encode(), timeout=120
            ).read()
            data: dict = json.loads(data_bytes)
            if cache_path is not None:
                with open(cache_path, "w") as f:
                    json.dump(data, f)
            return data
        except Exception as exc:
            if attempt == _MAX_RETRIES - 1:
                raise
            warnings.warn(
                f"Overpass request failed (attempt {attempt + 1}/{_MAX_RETRIES}): {exc}. Retrying..."
            )
            time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable: _overpass_fetch exceeded max retries")


def fetch_blocking_mask(
    bbox: tuple[float, float, float, float],
    blocking_leisure: frozenset[str],
    metric_crs: str = "EPSG:25830",
    cache_path: Optional[Path] = None,
) -> Optional[BaseGeometry]:
    s, w, n, e = bbox
    overpass_bbox = f"{s},{w},{n},{e}"
    leisure_re = "|".join(sorted(blocking_leisure))
    query = (
        f"[out:json][timeout:120];\n"
        f"(\n"
        f'  way["leisure"~"^({leisure_re})$"]({overpass_bbox});\n'
        f'  way["building"]({overpass_bbox});\n'
        f");\n"
        f"out geom;\n"
    )

    data = _overpass_fetch(query, cache_path)
    polys = _elements_to_polygons(data.get("elements", []))
    if not polys:
        return None

    gdf = gpd.GeoDataFrame(geometry=polys, crs="EPSG:4326").to_crs(metric_crs)
    mask = unary_union(gdf.geometry)
    return mask if not mask.is_empty else None


def _elements_to_polygons(elements: list[dict]) -> list[Polygon]:
    polys = []
    for el in elements:
        if el.get("type") != "way":
            continue
        coords = [(n["lon"], n["lat"]) for n in el.get("geometry", [])]
        if len(coords) < 4 or coords[0] != coords[-1]:
            continue
        try:
            p = Polygon(coords)
            if p.is_valid and not p.is_empty:
                polys.append(p)
        except Exception as exc:
            warnings.warn(f"Dropping malformed blocking polygon: {exc}")
    return polys
