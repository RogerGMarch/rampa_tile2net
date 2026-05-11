"""PedestrianPostProcessor — main orchestrator."""
from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.ops import unary_union

from tile2net.postprocess._blocking import fetch_blocking_mask
from tile2net.postprocess._gap_fill import fill_gaps
from tile2net.postprocess._width import estimate_edge_width, polygon_width
from tile2net.postprocess.result import PostProcessResult
from tile2net.postprocess.viario import OSMViarioSource, ViarioSource


# ── Configuration ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class PostProcessConfig:
    """Tunable parameters for :class:`PedestrianPostProcessor`.

    All distance values are in metres and are applied in the *metric_crs*
    projection.  The defaults were validated on the Valencia (Russafa) dataset.
    """

    metric_crs: str = "EPSG:25830"
    """Metric CRS for all spatial operations (UTM Zone 30 N for Valencia)."""

    simplify_tol: float = 2.5
    """Simplification tolerance applied to raw tile2net polygons."""

    buffer_close: float = 1.2
    """Open/close buffer radius to seal micro-gaps and remove spurs."""

    min_area: float = 5.0
    """Minimum polygon area (m²); smaller fragments are dropped."""

    osm_filter_dist: float = 10.0
    """Drop tile2net polygons further than this from any viario edge."""

    touch_buf: float = 3.0
    """Primary search radius for touching-polygon width estimation."""

    fallback_buf: float = 30.0
    """Wider search radius when nothing is found within *touch_buf*."""

    fill_cov_max: float = 0.60
    """Skip gap-fill for an OSM edge already ≥ this fraction covered."""

    half_w_clamp: tuple[float, float] = (1.2, 6.0)
    """Clamp range for estimated fill half-width (metres)."""

    blocking_leisure: frozenset = dataclasses.field(
        default_factory=lambda: frozenset({
            "stadium", "bleachers", "pitch", "sports_centre",
            "track", "swimming_pool", "ice_rink",
        })
    )
    """OSM leisure tag values treated as blocking areas."""


# ── Main class ─────────────────────────────────────────────────────────────────

class PedestrianPostProcessor:
    """Post-process tile2net outputs for an arbitrary municipality.

    The pipeline runs these steps in order:

    1. Load and clean tile2net polygon shapefile (simplify, buffer, area filter)
    2. Fetch reference viario (official city data or OSM)
    3. Drop polygons further than *osm_filter_dist* from any viario edge
    4. Fetch OSM blocking mask (buildings + leisure areas)
    5. Subtract blocking mask from polygons
    6. Gap-fill OSM footways and road-edge sidewalks
    7. Estimate polygon widths (2·area / perimeter)
    8. Load tile2net network shapefile
    9. Annotate each network edge with the width of nearby polygons
    10. Build a NetworkX MultiGraph with ``f_type``, ``width``, ``length``,
        ``source``, and ``geometry`` attributes on every edge

    Parameters
    ----------
    polygon_path:
        Path to the tile2net polygon shapefile (columns: ``f_type``, ``geometry``).
    network_path:
        Path to the tile2net network shapefile (columns: ``f_type``, ``geometry``).
    tiles_dir:
        Directory of ``{tx}_{ty}.png`` slippy tiles (optional, reserved for
        future visualisation helpers).
    viario:
        Source for the reference street/pedestrian network used in the distance
        filter.  Defaults to :class:`~tile2net.postprocess.OSMViarioSource`.
        Use :class:`~tile2net.postprocess.OfficialViarioSource` for city open-
        data (e.g. Valencia geoportal).
    osm_viario:
        Separate OSM source used exclusively for gap-fill (needs OSM
        ``highway`` / ``sidewalk`` tags).  Defaults to a fresh
        :class:`~tile2net.postprocess.OSMViarioSource`.  Can be the same
        instance as *viario* if *viario* is already an ``OSMViarioSource``.
    config:
        Tunable parameters.  Defaults to :class:`PostProcessConfig`.

    Example
    -------
    >>> from tile2net.postprocess import PedestrianPostProcessor, OfficialViarioSource
    >>> processor = PedestrianPostProcessor(
    ...     polygon_path="polygons/final/final.shp",
    ...     network_path="network/network.shp",
    ...     viario=OfficialViarioSource(
    ...         source_type="arcgis_rest",
    ...         url="https://geoportal.valencia.es/server/rest/services/"
    ...             "OPENDATA/UrbanismoEInfraestructuras/MapServer/223",
    ...     ),
    ... )
    >>> result = processor.run()
    >>> result.save("out/")
    """

    def __init__(
        self,
        polygon_path: str | Path,
        network_path: str | Path,
        tiles_dir: str | Path | None = None,
        viario: ViarioSource | None = None,
        osm_viario: ViarioSource | None = None,
        config: PostProcessConfig | None = None,
        blocking_cache_path: str | Path | None = None,
    ):
        self.polygon_path = Path(polygon_path)
        self.network_path = Path(network_path)
        self.tiles_dir = Path(tiles_dir) if tiles_dir else None
        self._viario = viario  # distance filter
        self._osm_viario = osm_viario  # gap fill (always OSM)
        self.config = config or PostProcessConfig()
        self._bbox: tuple[float, float, float, float] | None = None
        self._blocking_cache = Path(blocking_cache_path) if blocking_cache_path else None

    # ── public ────────────────────────────────────────────────────────────

    def run(self) -> PostProcessResult:
        """Execute the full post-processing pipeline and return results."""
        cfg = self.config

        # 1–2: load + clean polygons
        gdf = self._load_polygons()
        gdf = self._clean_polygons(gdf)

        # derive bounding box in WGS84 from the polygon extent
        bbox = self._compute_bbox(gdf)

        # 3: fetch reference viario & distance filter
        ref_viario = self._fetch_reference_viario(bbox)
        gdf = self._distance_filter(gdf, ref_viario)

        # 4–5: blocking mask subtraction
        try:
            block_mask = self._fetch_blocking(bbox)
        except Exception:
            warnings.warn("Blocking mask fetch failed (likely area too large) — skipping")
            block_mask = None
        gdf = self._subtract_blocking(gdf, block_mask)

        # 6: gap fill using OSM (footways + road-edge sidewalks)
        osm_viario = self._fetch_osm_viario(bbox)
        gdf = self._gap_fill(gdf, osm_viario, block_mask)

        # 7: estimate polygon widths
        gdf = self._estimate_widths(gdf)

        # 8–9: load + annotate network
        net = self._load_network()
        net = self._annotate_network(net, gdf)

        # 10: build NetworkX graph
        graph = self._build_graph(net)

        return PostProcessResult(polygons=gdf, network=net, graph=graph)

    # ── private helpers ───────────────────────────────────────────────────

    def _load_polygons(self) -> gpd.GeoDataFrame:
        gdf = gpd.read_file(self.polygon_path)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        return gdf.to_crs(self.config.metric_crs)

    def _clean_polygons(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        cfg = self.config
        gdf = gdf.copy()
        gdf["geometry"] = (
            gdf.geometry
               .simplify(cfg.simplify_tol, preserve_topology=True)
               .buffer(cfg.buffer_close)
               .buffer(-cfg.buffer_close)
        )
        gdf = gdf[gdf.geometry.is_valid & ~gdf.geometry.is_empty]
        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
        gdf = gdf[gdf.area > cfg.min_area].reset_index(drop=True)
        if "source" not in gdf.columns:
            gdf["source"] = "tile2net"
        return gdf

    def _compute_bbox(self, gdf: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
        """Return (S, W, N, E) in WGS84 from the polygon GeoDataFrame."""
        w, s, e, n = gdf.to_crs("EPSG:4326").total_bounds  # (minx, miny, maxx, maxy)
        self._bbox = (s, w, n, e)
        return self._bbox

    def _fetch_reference_viario(self, bbox: tuple) -> gpd.GeoDataFrame:
        if self._viario is None:
            self._viario = OSMViarioSource()
        gdf = self._viario.fetch_edges(bbox)
        return gdf.to_crs(self.config.metric_crs)

    def _fetch_osm_viario(self, bbox: tuple) -> gpd.GeoDataFrame:
        if self._osm_viario is None:
            # if the reference viario is already OSMViarioSource, reuse its data
            if isinstance(self._viario, OSMViarioSource):
                self._osm_viario = self._viario
            else:
                self._osm_viario = OSMViarioSource()
        gdf = self._osm_viario.fetch_edges(bbox)
        return gdf.to_crs(self.config.metric_crs)

    def _distance_filter(
        self, gdf: gpd.GeoDataFrame, viario_gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        if viario_gdf.empty:
            warnings.warn("Viario is empty — skipping distance filter.")
            return gdf
        net_union = unary_union(viario_gdf.geometry)
        mask = gdf.geometry.distance(net_union) <= self.config.osm_filter_dist
        return gdf[mask].reset_index(drop=True)

    def _fetch_blocking(self, bbox: tuple):
        return fetch_blocking_mask(
            bbox,
            blocking_leisure=self.config.blocking_leisure,
            metric_crs=self.config.metric_crs,
            cache_path=self._blocking_cache,
        )

    def _subtract_blocking(self, gdf: gpd.GeoDataFrame, block_mask) -> gpd.GeoDataFrame:
        if block_mask is None or block_mask.is_empty:
            return gdf
        gdf = gdf.copy()
        gdf["geometry"] = gdf.geometry.difference(block_mask)
        gdf = gdf.explode(index_parts=False).reset_index(drop=True)
        gdf = gdf[gdf.geometry.geom_type == "Polygon"]
        gdf = gdf[gdf.area > self.config.min_area].reset_index(drop=True)
        return gdf

    def _gap_fill(
        self,
        gdf: gpd.GeoDataFrame,
        osm_viario: gpd.GeoDataFrame,
        block_mask,
    ) -> gpd.GeoDataFrame:
        sw_only = gdf[gdf["f_type"] == "sidewalk"].copy()
        poly_union = unary_union(gdf.geometry)

        # build template row from first sidewalk (preserves column schema)
        if not sw_only.empty:
            ref_row = sw_only.iloc[0].drop("geometry").to_dict()
        else:
            ref_row = {c: None for c in gdf.columns if c != "geometry"}

        fills = fill_gaps(
            viario_gdf_m=osm_viario,
            sw_gdf_m=sw_only,
            poly_union_m=poly_union,
            block_mask=block_mask,
            config=self.config,
            ref_row=ref_row,
        )
        if not fills:
            return gdf

        fills_gdf = gpd.GeoDataFrame(fills, geometry="geometry", crs=self.config.metric_crs)
        return pd.concat([gdf, fills_gdf], ignore_index=True)

    def _estimate_widths(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        gdf = gdf.copy()
        if "width" not in gdf.columns:
            gdf["width"] = float("nan")
        # fill width for tile2net rows (gap-fill rows already have width set)
        needs_width = gdf["width"].isna() | (gdf.get("source", "") == "tile2net")
        gdf.loc[needs_width, "width"] = (
            gdf.loc[needs_width, "geometry"].apply(polygon_width)
        )
        return gdf

    def _load_network(self) -> gpd.GeoDataFrame:
        net = gpd.read_file(self.network_path)
        if net.crs is None:
            net = net.set_crs("EPSG:4326")
        net = net.to_crs(self.config.metric_crs)
        if "source" not in net.columns:
            net["source"] = "tile2net"
        return net

    def _annotate_network(
        self, net: gpd.GeoDataFrame, gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        net = net.copy()
        net["width"] = float("nan")
        net["width_source"] = "none"
        net["length"] = net.geometry.length

        n_total = len(net)
        bad_mask = net.geometry.isna() | net.geometry.is_empty
        n_bad = int(bad_mask.sum())

        sindex = gdf.sindex

        def _row_width(row):
            return estimate_edge_width(
                row.geometry,
                gdf,
                sindex,
                touch_buf=self.config.touch_buf,
                fallback_buf=self.config.fallback_buf,
                half_w_clamp=self.config.half_w_clamp,
            )

        net["width"] = net.apply(_row_width, axis=1)
        n_spatial = int(net["width"].notna().sum())
        net.loc[net["width"].notna(), "width_source"] = "spatial"

        n_propagated = 0
        nan_before = net["width"].isna()
        if nan_before.any() and not nan_before.all():
            net = self._propagate_edge_widths(net)
            filled = nan_before & net["width"].notna()
            n_propagated = int(filled.sum())
            net.loc[filled, "width_source"] = "propagation"

        n_median = 0
        still_nan = net["width"].isna()
        if still_nan.any():
            known = net["width"].dropna()
            fallback = float(known.median()) if not known.empty else 3.0
            n_median = int(still_nan.sum())
            net.loc[still_nan, "width"] = fallback
            net.loc[still_nan, "width_source"] = "median"

        parts = [f"spatial={n_spatial}"]
        if n_propagated:
            parts.append(f"propagation={n_propagated}")
        if n_median:
            parts.append(f"median={n_median}")
        if n_bad:
            parts.append(f"bad_geom={n_bad}")
        warnings.warn(
            f"Width assignment ({n_total} network edges): {'  '.join(parts)}"
        )
        return net

    @staticmethod
    def _edge_endpoints(geom):
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            return [tuple(np.round(coords[0], 6)), tuple(np.round(coords[-1], 6))]
        elif geom.geom_type == "MultiLineString":
            pts = set()
            for part in geom.geoms:
                if not part.is_empty:
                    cs = list(part.coords)
                    pts.add(tuple(np.round(cs[0], 6)))
                    pts.add(tuple(np.round(cs[-1], 6)))
            return list(pts)
        return []

    def _propagate_edge_widths(self, net: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        node_edges: dict[tuple, list[tuple[int, float]]] = {}
        for i, row in net.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            for node in self._edge_endpoints(geom):
                node_edges.setdefault(node, []).append((i, row.get("width")))

        for i, row in net.iterrows():
            if not np.isnan(row.get("width", float("nan"))):
                continue
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            connected = []
            for node in self._edge_endpoints(geom):
                for idx, w in node_edges.get(node, []):
                    if idx != i and w is not None and not np.isnan(w):
                        connected.append(w)
            if connected:
                net.at[i, "width"] = float(np.mean(connected))
        return net

    def _build_graph(self, net: gpd.GeoDataFrame) -> nx.MultiGraph:
        G = nx.MultiGraph()
        for _, row in net.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type == "LineString":
                parts = [geom]
            elif geom.geom_type == "MultiLineString":
                parts = list(geom.geoms)
            else:
                continue

            base_attrs = dict(
                f_type=row.get("f_type", "sidewalk"),
                width=float(row.get("width") if row.get("width") is not None else float("nan")),
                width_source=str(row.get("width_source", "unknown")),
                source=str(row.get("source", "tile2net")),
            )
            for part in parts:
                if part.is_empty:
                    continue
                coords = list(part.coords)
                u = tuple(np.round(coords[0], 6))
                v = tuple(np.round(coords[-1], 6))
                if not G.has_node(u):
                    G.add_node(u, x=u[0], y=u[1], geometry=Point(u))
                if not G.has_node(v):
                    G.add_node(v, x=v[0], y=v[1], geometry=Point(v))
                G.add_edge(u, v, **base_attrs,
                           length=float(row.get("length", part.length)),
                           geometry=part)
        return G
