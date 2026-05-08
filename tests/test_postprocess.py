"""Tests for the post-processing pipeline — width coverage, graph sanity, DuckDB round-trip."""
from __future__ import annotations

import pickle
import tempfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, Polygon

from tile2net.duckdb import (
    get_duckdb_connection,
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
from tile2net.postprocess import (
    OSMViarioSource,
    PedestrianPostProcessor,
    PostProcessConfig,
)

# Paths relative to repo root (assumes tests are run with `uv run pytest tests/`)
DATA_DIR = Path("test_output/valencia_center/valencia_center")
POLYGON_PATH = DATA_DIR / "polygons" / "final" / "final.shp"
NETWORK_DIR = sorted((DATA_DIR / "network").iterdir())[-1]
NETWORK_PATH = NETWORK_DIR / f"{NETWORK_DIR.name}.shp"

OSM_CACHE = Path("/tmp/osm_center_ped.json")
BLOCKING_CACHE = Path("/tmp/osm_center_blocking.json")
OUT_DIR = Path("test_output/postprocess_test")
DEFAULT_HALF_CLAMP = (1.2, 6.0)


@pytest.fixture(scope="session")
def processor():
    return PedestrianPostProcessor(
        polygon_path=POLYGON_PATH,
        network_path=NETWORK_PATH,
        viario=OSMViarioSource(cache_path=OSM_CACHE),
        config=PostProcessConfig(),
        blocking_cache_path=BLOCKING_CACHE,
    )


@pytest.fixture(scope="session")
def result(processor):
    return processor.run()


class TestWidthCoverage:
    def test_network_no_nan_widths(self, result):
        assert not result.network["width"].isna().any(), (
            f"{result.network['width'].isna().sum()} network edges have NaN width"
        )

    def test_network_width_positive(self, result):
        assert (result.network["width"] > 0).all(), "Some widths are <= 0"

    def test_network_width_within_clamp(self, result):
        lo, hi = 1.2, 6.0
        full_lo, full_hi = lo * 2, hi * 2
        w = result.network["width"]
        out = w[(w < full_lo) | (w > full_hi)]
        assert out.empty, (
            f"{len(out)} edges outside clamp [{full_lo}, {full_hi}]: "
            f"values={out.tolist()}"
        )

    def test_polygons_have_width(self, result):
        assert not result.polygons["width"].isna().all(), "All polygon widths are NaN"
        assert (result.polygons["width"] > 0).all(), (
            f"{(result.polygons['width'] <= 0).sum()} polygons have width <= 0"
        )

    def test_polygon_f_types(self, result):
        valid = {"sidewalk", "road", "crosswalk"}
        unknown = set(result.polygons["f_type"].unique()) - valid
        assert not unknown, f"Unknown f_type values: {unknown}"

    def test_network_width_source_column(self, result):
        assert "width_source" in result.network.columns, "Network missing width_source column"
        valid = {"spatial", "propagation", "median", "none"}
        unknown = set(result.network["width_source"].unique()) - valid
        assert not unknown, f"Unknown width_source values: {unknown}"

    def test_width_source_counts_match_warning(self, result):
        vc = result.network["width_source"].value_counts()
        n_spatial = int(vc.get("spatial", 0))
        n_propagation = int(vc.get("propagation", 0))
        n_median = int(vc.get("median", 0))
        total = n_spatial + n_propagation + n_median
        assert total == len(result.network), (
            f"width_source sum {total} != total edges {len(result.network)}"
        )
        # spatial should be the dominant source
        assert n_spatial > n_propagation + n_median, (
            f"spatial={n_spatial} should dominate propagation={n_propagation} "
            f"+ median={n_median}"
        )


class TestGraphSanity:
    def test_graph_has_edges(self, result):
        assert result.graph.number_of_edges() > 0

    def test_graph_edges_have_width(self, result):
        missing = []
        for u, v, k, data in result.graph.edges(data=True, keys=True):
            w = data.get("width")
            if w is None or np.isnan(w):
                missing.append((u, v, k))
        assert not missing, f"{len(missing)} graph edges have missing/NaN width"

    def test_graph_edges_have_length(self, result):
        for u, v, k, data in result.graph.edges(data=True, keys=True):
            assert data.get("length", 0) > 0, f"Edge {(u, v, k)} has zero length"

    def test_graph_edges_have_geometry(self, result):
        for u, v, k, data in result.graph.edges(data=True, keys=True):
            assert data.get("geometry") is not None, f"Edge {(u, v, k)} missing geometry"


class TestRoundTrip:
    @pytest.fixture(scope="class")
    def saved_dir(self, result):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        result.save(OUT_DIR)
        return OUT_DIR

    def test_shp_written(self, saved_dir):
        assert (saved_dir / "polygons" / "polygons.shp").exists()
        assert (saved_dir / "network" / "network.shp").exists()

    def test_gpickle_roundtrip(self, saved_dir):
        path = saved_dir / "graph.gpickle"
        assert path.exists()
        with open(path, "rb") as f:
            g = pickle.load(f)
        assert isinstance(g, nx.MultiGraph)
        assert g.number_of_edges() > 0

    def test_graphml_written(self, saved_dir):
        path = saved_dir / "graph.graphml"
        assert path.exists()
        assert path.stat().st_size > 0


# ── DuckDB round-trip tests ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def duck_con(result):
    """Session-scoped DuckDB connection pre-loaded with the processor output."""
    con = get_duckdb_connection(tempfile.mktemp(suffix=".db"))
    write_polygons(con, "test_project", result.polygons)
    write_network(con, "test_project", result.network)
    write_graph(con, "test_project", result.graph)
    test_tiles = {(0, 0): b"tile_png_data_00", (1, 2): b"tile_png_data_12"}
    write_tiles(con, "tile_project", test_tiles)
    yield con
    con.close()


class TestDuckDBPolygons:
    def test_polygon_count(self, result, duck_con):
        gdf = read_polygons(duck_con, "test_project")
        assert len(gdf) == len(result.polygons), (
            f"Expected {len(result.polygons)} polygons, got {len(gdf)}"
        )

    def test_polygon_columns(self, duck_con):
        gdf = read_polygons(duck_con, "test_project")
        for col in ("f_type", "width", "source", "geometry"):
            assert col in gdf.columns, f"Missing column: {col}"

    def test_polygon_geometry_types(self, duck_con):
        gdf = read_polygons(duck_con, "test_project")
        valid = {"Polygon", "MultiPolygon"}
        bad = gdf[~gdf.geometry.geom_type.isin(valid)]
        assert bad.empty, (
            f"{len(bad)} geometries not Polygon/MultiPolygon: "
            f"{bad.geometry.geom_type.unique()}"
        )

    def test_polygon_widths_no_nan(self, duck_con):
        gdf = read_polygons(duck_con, "test_project")
        assert not gdf["width"].isna().all(), "All polygon widths are NaN"
        assert (gdf["width"] > 0).all(), (
            f"{(gdf['width'] <= 0).sum()} polygons have width <= 0"
        )

    def test_polygon_f_types_preserved(self, result, duck_con):
        gdf = read_polygons(duck_con, "test_project")
        expected = set(result.polygons["f_type"].unique())
        actual = set(gdf["f_type"].unique())
        missing = expected - actual
        assert not missing, f"f_type values lost in round-trip: {missing}"


class TestDuckDBNetwork:
    def test_network_count(self, result, duck_con):
        gdf = read_network(duck_con, "test_project")
        assert len(gdf) == len(result.network), (
            f"Expected {len(result.network)} edges, got {len(gdf)}"
        )

    def test_network_columns(self, duck_con):
        gdf = read_network(duck_con, "test_project")
        for col in ("f_type", "width", "width_source", "length", "source", "geometry"):
            assert col in gdf.columns, f"Missing column: {col}"

    def test_network_no_nan_widths(self, duck_con):
        gdf = read_network(duck_con, "test_project")
        assert not gdf["width"].isna().any(), (
            f"{gdf['width'].isna().sum()} network edges have NaN width after round-trip"
        )

    def test_network_widths_within_clamp(self, duck_con):
        gdf = read_network(duck_con, "test_project")
        lo, hi = DEFAULT_HALF_CLAMP
        w = gdf["width"]
        out = w[(w < lo * 2) | (w > hi * 2)]
        assert out.empty, (
            f"{len(out)} round-tripped edges outside clamp "
            f"[{lo*2}, {hi*2}]: {out.tolist()}"
        )

    def test_network_lengths_positive(self, duck_con):
        gdf = read_network(duck_con, "test_project")
        zero = gdf[gdf["length"] <= 0]
        assert zero.empty, f"{len(zero)} network edges have zero/negative length"

    def test_network_geometry_types(self, duck_con):
        gdf = read_network(duck_con, "test_project")
        valid = {"LineString", "MultiLineString"}
        bad = gdf[~gdf.geometry.geom_type.isin(valid)]
        assert bad.empty, (
            f"{len(bad)} geometries not LineString/MultiLineString: "
            f"{bad.geometry.geom_type.unique()}"
        )

    def test_network_crs(self, duck_con):
        gdf = read_network(duck_con, "test_project")
        assert gdf.crs is not None, "Network GeoDataFrame has no CRS"


class TestDuckDBGraph:
    def test_graph_edge_count(self, result, duck_con):
        g = read_graph(duck_con, "test_project")
        assert g.number_of_edges() == result.graph.number_of_edges(), (
            f"Expected {result.graph.number_of_edges()} edges, "
            f"got {g.number_of_edges()}"
        )

    def test_graph_node_count(self, result, duck_con):
        g = read_graph(duck_con, "test_project")
        assert g.number_of_nodes() == result.graph.number_of_nodes(), (
            f"Expected {result.graph.number_of_nodes()} nodes, "
            f"got {g.number_of_nodes()}"
        )

    def test_graph_type(self, duck_con):
        g = read_graph(duck_con, "test_project")
        assert isinstance(g, nx.MultiGraph), f"Expected MultiGraph, got {type(g)}"

    def test_graph_edges_have_width(self, duck_con):
        g = read_graph(duck_con, "test_project")
        missing = []
        for u, v, k, data in g.edges(data=True, keys=True):
            w = data.get("width")
            if w is None or np.isnan(w):
                missing.append((u, v, k))
        assert not missing, f"{len(missing)} graph edges have missing/NaN width"

    def test_graph_edges_have_length(self, duck_con):
        g = read_graph(duck_con, "test_project")
        for u, v, k, data in g.edges(data=True, keys=True):
            assert data.get("length", 0) > 0, f"Edge {(u, v, k)} has zero length"

    def test_graph_edges_have_geometry(self, duck_con):
        g = read_graph(duck_con, "test_project")
        for u, v, k, data in g.edges(data=True, keys=True):
            geom = data.get("geometry")
            assert geom is not None, f"Edge {(u, v, k)} missing geometry"
            assert isinstance(geom, (LineString, MultiLineString)), (
                f"Edge {(u, v, k)} has non-LineString geometry type"
            )

    def test_graph_edges_have_f_type_and_source(self, duck_con):
        g = read_graph(duck_con, "test_project")
        for u, v, k, data in g.edges(data=True, keys=True):
            assert "f_type" in data, f"Edge {(u, v, k)} missing f_type"
            assert "source" in data, f"Edge {(u, v, k)} missing source"
            assert "width_source" in data, f"Edge {(u, v, k)} missing width_source"
            assert data["width_source"] in ("spatial", "propagation", "median", ""), (
                f"Edge {(u, v, k)} bad width_source: {data.get('width_source')!r}"
            )

    def test_graph_nodes_have_coords(self, duck_con):
        g = read_graph(duck_con, "test_project")
        for node, data in g.nodes(data=True):
            assert "x" in data, f"Node {node} missing x"
            assert "y" in data, f"Node {node} missing y"
            assert "geometry" in data, f"Node {node} missing geometry"

    def test_graph_is_connected(self, duck_con):
        g = read_graph(duck_con, "test_project")
        # pedestrian network may be disjoint; test at least one component has edges
        cc = list(nx.connected_components(g))
        assert len(cc) >= 1, "Graph has zero connected components"
        sizes = [len(c) for c in cc if len(c) > 1]
        assert sizes, "No component has more than 1 node"


class TestDuckDBTiles:
    def test_write_and_read(self, duck_con):
        assert read_tile(duck_con, "tile_project", 0, 0) == b"tile_png_data_00"
        assert read_tile(duck_con, "tile_project", 1, 2) == b"tile_png_data_12"

    def test_missing_tile(self, duck_con):
        assert read_tile(duck_con, "tile_project", 99, 99) is None

    def test_list_tiles(self, duck_con):
        tiles = list_tiles(duck_con, "tile_project")
        assert len(tiles) == 2
        assert (0, 0) in tiles
        assert (1, 2) in tiles

    def test_overwrite_tile(self, duck_con):
        write_tiles(duck_con, "tile_project", {(0, 0): b"updated_data"})
        assert read_tile(duck_con, "tile_project", 0, 0) == b"updated_data"
        # restore original for other tests
        write_tiles(duck_con, "tile_project", {(0, 0): b"tile_png_data_00"})


class TestDuckDBEmpty:
    """Verifying reads on a project that was never written return empty, not crash."""

    def test_empty_polygons(self, duck_con):
        gdf = read_polygons(duck_con, "nonexistent")
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 0
        assert "geometry" in gdf.columns

    def test_empty_network(self, duck_con):
        gdf = read_network(duck_con, "nonexistent")
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 0
        assert "geometry" in gdf.columns

    def test_empty_graph(self, duck_con):
        g = read_graph(duck_con, "nonexistent")
        assert isinstance(g, nx.MultiGraph)
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0

    def test_empty_tiles(self, duck_con):
        assert list_tiles(duck_con, "nonexistent") == []
        assert read_tile(duck_con, "nonexistent", 0, 0) is None
