"""Viario (street/pedestrian network) source abstraction."""
from __future__ import annotations

import abc
import json
import time
import urllib.request
import warnings
from pathlib import Path
from typing import Literal, Optional

import geopandas as gpd
from shapely.geometry import LineString

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_MAX_RETRIES = 3

_PED_HIGHWAY_TYPES = (
    "footway", "path", "pedestrian", "steps", "living_street", "service",
    "primary", "secondary", "tertiary", "residential", "unclassified", "trunk",
)


class ViarioSource(abc.ABC):
    """Abstract base for pedestrian/street network sources."""

    @abc.abstractmethod
    def fetch_edges(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """Return GeoDataFrame of LineStrings in EPSG:4326 covering bbox (S, W, N, E).

        The GeoDataFrame should include at minimum a 'geometry' column.
        OSM-derived sources also include 'highway' and 'sidewalk' columns,
        which are required for gap-fill logic.
        """

    def name(self) -> str:
        return self.__class__.__name__


class OSMViarioSource(ViarioSource):
    """Fetch pedestrian network from OpenStreetMap via Overpass API.

    Produces columns: geometry, highway, sidewalk, name, osm_id.
    These are needed by the gap-fill step.
    """

    def __init__(self, cache_path: str | Path | None = None):
        self._cache = Path(cache_path) if cache_path else None

    def _overpass_fetch(self, query: str) -> dict:
        if self._cache and self._cache.exists():
            with open(self._cache) as f:
                return json.load(f)

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    _OVERPASS_URL,
                    data=query.encode(),
                    headers={"User-Agent": "tile2net/0.4", "Accept": "application/json"},
                )
                data_bytes = urllib.request.urlopen(req, timeout=120).read()
                data: dict = json.loads(data_bytes)
                if self._cache:
                    with open(self._cache, "w") as f:
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

    def fetch_edges(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        s, w, n, e = bbox
        overpass_bbox = f"{s},{w},{n},{e}"
        highway_re = "|".join(_PED_HIGHWAY_TYPES)
        query = (
            f"[out:json][timeout:120];\n"
            f"(\n"
            f'  way["highway"~"^({highway_re})$"]({overpass_bbox});\n'
            f");\n"
            f"out geom;\n"
        )

        data = self._overpass_fetch(query)
        return _osm_elements_to_gdf(data.get("elements", []))


class OfficialViarioSource(ViarioSource):
    """Fetch street network from an official city open-data source.

    Supported source_type values:
    - 'arcgis_rest'  : ArcGIS REST MapServer layer (e.g. Valencia geoportal)
    - 'wfs'          : OGC WFS endpoint (via geopandas read_file)
    - 'geojson_url'  : direct GeoJSON download URL
    - 'local_file'   : already-downloaded file (Shapefile, GeoJSON, GeoPackage …)

    The official data is used for the *distance filter* (drop tile2net polygons
    far from any street).  Gap-fill always falls back to OSM because it needs
    OSM highway/sidewalk tags.  If the official service is unreachable the source
    automatically falls back to OSMViarioSource.

    Example — Valencia geoportal:
        OfficialViarioSource(
            source_type='arcgis_rest',
            url='https://geoportal.valencia.es/server/rest/services/'
                'OPENDATA/UrbanismoEInfraestructuras/MapServer/223',
        )
    """

    def __init__(
        self,
        source_type: Literal["arcgis_rest", "wfs", "geojson_url", "local_file"],
        url: str,
        cache_path: str | Path | None = None,
        fallback: ViarioSource | None = None,
    ):
        self._source_type = source_type
        self._url = url
        self._cache = Path(cache_path) if cache_path else None
        self._fallback = fallback or OSMViarioSource()

    def fetch_edges(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        try:
            if self._source_type == "arcgis_rest":
                gdf = self._fetch_arcgis_rest(bbox)
            elif self._source_type in ("wfs", "geojson_url"):
                gdf = self._fetch_url(bbox)
            elif self._source_type == "local_file":
                gdf = self._fetch_local(bbox)
            else:
                raise ValueError(f"Unknown source_type: {self._source_type!r}")
        except (urllib.error.URLError, ValueError, OSError) as exc:
            warnings.warn(
                f"OfficialViarioSource ({self._source_type}) failed: {exc}. "
                "Falling back to OSMViarioSource."
            )
            return self._fallback.fetch_edges(bbox)

        # ensure required columns exist (OSM tags absent from official data)
        for col in ("highway", "sidewalk", "name", "osm_id"):
            if col not in gdf.columns:
                gdf[col] = ""
        return gdf

    # ── private helpers ───────────────────────────────────────────────────

    def _clip_and_filter(
        self, gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float]
    ) -> gpd.GeoDataFrame:
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        else:
            gdf = gdf.to_crs("EPSG:4326")
        s, w, n, e = bbox
        gdf = gdf.cx[w:e, s:n]
        return gdf[
            gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])
        ].copy()

    def _fetch_arcgis_rest(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        s, w, n, e = bbox
        params = (
            f"where=1%3D1"
            f"&geometry={w},{s},{e},{n}"
            f"&geometryType=esriGeometryEnvelope"
            f"&inSR=4326"
            f"&spatialRel=esriSpatialRelIntersects"
            f"&outSR=4326"
            f"&f=geojson"
            f"&returnGeometry=true"
            f"&outFields=*"
        )
        url = f"{self._url}/query?{params}"
        if self._cache and self._cache.exists():
            gdf = gpd.read_file(self._cache)
        else:
            gdf = gpd.read_file(url)
            if self._cache:
                gdf.to_file(self._cache, driver="GeoJSON")
        return self._clip_and_filter(gdf, bbox)

    def _fetch_url(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        if self._cache and self._cache.exists():
            gdf = gpd.read_file(self._cache)
        else:
            gdf = gpd.read_file(self._url)
            if self._cache:
                gdf.to_file(self._cache, driver="GeoJSON")
        return self._clip_and_filter(gdf, bbox)

    def _fetch_local(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        gdf = gpd.read_file(self._url)
        return self._clip_and_filter(gdf, bbox)


# ── helpers ───────────────────────────────────────────────────────────────

def _osm_elements_to_gdf(elements: list[dict]) -> gpd.GeoDataFrame:
    """Convert Overpass API way elements to a GeoDataFrame of LineStrings."""
    rows = []
    for el in elements:
        if el.get("type") != "way":
            continue
        coords = [(n["lon"], n["lat"]) for n in el.get("geometry", [])]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        rows.append({
            "geometry": LineString(coords),
            "highway": tags.get("highway", ""),
            "sidewalk": tags.get("sidewalk", ""),
            "name": tags.get("name", ""),
            "osm_id": el.get("id"),
        })
    if not rows:
        return gpd.GeoDataFrame(
            columns=["geometry", "highway", "sidewalk", "name", "osm_id"],
            geometry="geometry",
            crs="EPSG:4326",
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
