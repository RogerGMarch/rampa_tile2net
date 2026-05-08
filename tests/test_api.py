"""Integration tests for the Tile2Net REST API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tile2net.api.config import ApiConfig, get_api_config
from tile2net.api.main import create_app

# Override config to use temp paths
import tempfile
from pathlib import Path


@pytest.fixture(scope="module")
def temp_home():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture(scope="module")
def api_config(temp_home):
    cfg = ApiConfig(
        data_root=temp_home,
        registry_path=temp_home / "registry.db",
    )
    # monkey-patch the module-level cached config
    import tile2net.api.config as cfg_mod
    old = cfg_mod._config
    cfg_mod._config = cfg
    yield cfg
    cfg_mod._config = old


@pytest.fixture(scope="module")
def client(api_config):
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestProjectsCRUD:
    PROJECT = {
        "name": "test_valencia",
        "location": "39.469,-0.381,39.478,-0.369",
        "zoom": 19,
        "crs": 4326,
        "metric_crs": "EPSG:25830",
        "viario_type": "osm",
    }

    def test_create_project(self, client):
        resp = client.post("/projects/", json=self.PROJECT)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["name"] == "test_valencia"
        assert data["status"] == "created"
        assert data["bbox_wgs84"] is not None
        assert len(data["bbox_wgs84"]) == 4

    def test_create_duplicate_rejected(self, client):
        resp = client.post("/projects/", json=self.PROJECT)
        assert resp.status_code == 409

    def test_list_projects(self, client):
        resp = client.get("/projects/")
        assert resp.status_code == 200
        projects = resp.json()["projects"]
        assert len(projects) >= 1
        names = [p["name"] for p in projects]
        assert "test_valencia" in names

    def test_get_project(self, client):
        resp = client.get("/projects/test_valencia")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test_valencia"
        assert data["zoom"] == 19
        assert data["metric_crs"] == "EPSG:25830"

    def test_patch_project(self, client):
        resp = client.patch(
            "/projects/test_valencia",
            json={"metric_crs": "EPSG:32630"},
        )
        assert resp.status_code == 200
        assert resp.json()["metric_crs"] == "EPSG:32630"

    def test_delete_project(self, client):
        resp = client.delete("/projects/test_valencia")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        # verify gone
        resp = client.get("/projects/test_valencia")
        assert resp.status_code == 404


class TestPipelineEndpoints:
    def test_status_no_pipeline(self, client):
        resp = client.get("/projects/test_valencia/pipeline/status")
        assert resp.status_code == 404

    def test_cancel_no_pipeline(self, client):
        resp = client.delete("/projects/test_valencia/pipeline")
        assert resp.status_code == 404


class TestDataEndpoints:
    """Test data queries using the pre-built valencia center DuckDB."""

    @pytest.fixture(scope="class")
    def populated_client(self, client):
        """Pre-populate a project's DuckDB with the valencia center data."""
        from tile2net.duckdb import (
            get_duckdb_connection,
            write_graph,
            write_network,
            write_polygons,
        )
        from tile2net.postprocess import (
            OSMViarioSource,
            PedestrianPostProcessor,
            PostProcessConfig,
        )

        # create project in registry
        proj = {
            "name": "valencia_data_test",
            "location": "39.469,-0.381,39.478,-0.369",
            "zoom": 19,
            "crs": 4326,
            "metric_crs": "EPSG:25830",
            "viario_type": "osm",
        }
        client.post("/projects/", json=proj)

        # run processor and write to project DB
        DATA = Path("test_output/valencia_center/valencia_center")
        POLY = DATA / "polygons" / "final" / "final.shp"
        NET_DIR = sorted((DATA / "network").iterdir())[-1]
        NET = NET_DIR / f"{NET_DIR.name}.shp"

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            proc = PedestrianPostProcessor(
                polygon_path=POLY,
                network_path=NET,
                viario=OSMViarioSource(cache_path="/tmp/osm_center_ped.json"),
                config=PostProcessConfig(),
                blocking_cache_path="/tmp/osm_center_blocking.json",
            )
            result = proc.run()

        con = get_duckdb_connection("/tmp/api_test_valencia.db")
        write_polygons(con, "valencia_data_test", result.polygons)
        write_network(con, "valencia_data_test", result.network)
        write_graph(con, "valencia_data_test", result.graph)
        con.close()

        # symlink the DB to where the API expects it
        import tile2net.api.config as cfg_mod
        proj_dir = cfg_mod._config.data_root / "projects" / "valencia_data_test"
        proj_dir.mkdir(parents=True, exist_ok=True)
        target = proj_dir / "tile2net.db"
        if not target.exists():
            import shutil
            shutil.copy("/tmp/api_test_valencia.db", target)

        yield client

        # cleanup
        import os
        os.remove("/tmp/api_test_valencia.db")
        os.remove("/tmp/api_test_valencia.db.wal") if os.path.exists("/tmp/api_test_valencia.db.wal") else None
        client.delete("/projects/valencia_data_test")

    def test_polygons_empty_query(self, populated_client):
        resp = populated_client.get("/projects/valencia_data_test/polygons")
        assert resp.status_code == 200
        fc = resp.json()
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) > 0

    def test_polygons_filter_f_type(self, populated_client):
        resp = populated_client.get(
            "/projects/valencia_data_test/polygons",
            params={"f_type": "sidewalk", "limit": 5},
        )
        assert resp.status_code == 200
        feats = resp.json()["features"]
        assert len(feats) <= 5
        assert all(f["properties"].get("f_type") == "sidewalk" for f in feats)

    def test_polygons_bbox_filter(self, populated_client):
        resp = populated_client.get(
            "/projects/valencia_data_test/polygons",
            params={"bbox": "39.47,-0.38,39.48,-0.37"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["features"]) > 0

    def test_polygons_invalid_bbox(self, populated_client):
        resp = populated_client.get(
            "/projects/valencia_data_test/polygons",
            params={"bbox": "invalid"},
        )
        assert resp.status_code == 400

    def test_network(self, populated_client):
        resp = populated_client.get("/projects/valencia_data_test/network")
        assert resp.status_code == 200
        fc = resp.json()
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) > 0

    def test_network_filter_width(self, populated_client):
        resp = populated_client.get(
            "/projects/valencia_data_test/network",
            params={"min_width": 3.0, "limit": 10},
        )
        assert resp.status_code == 200
        feats = resp.json()["features"]
        for f in feats:
            assert f["properties"].get("width", 0) >= 3.0

    def test_graph_summary(self, populated_client):
        resp = populated_client.get("/projects/valencia_data_test/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] > 0
        assert data["edge_count"] > 0
        assert data["total_length_m"] > 0
        assert "crs" in data

    def test_graph_edges(self, populated_client):
        resp = populated_client.get("/projects/valencia_data_test/graph/edges")
        assert resp.status_code == 200
        fc = resp.json()
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) > 0

    def test_graph_edges_filter(self, populated_client):
        resp = populated_client.get(
            "/projects/valencia_data_test/graph/edges",
            params={"min_width": 3.0, "limit": 5},
        )
        assert resp.status_code == 200
        feats = resp.json()["features"]
        assert len(feats) <= 5

    def test_missing_project(self, populated_client):
        resp = populated_client.get("/projects/nonexistent/polygons")
        assert resp.status_code == 404
