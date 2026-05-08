"""FastAPI application factory for the Tile2Net REST API."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tile2net.api.exceptions import PipelineConflictError, ProjectNotFoundError
from tile2net.api.routers import data, pipeline, projects

DESCRIPTION = r"""
Tile2Net is a pedestrian-network extraction pipeline that turns aerial imagery
into a weighted **NetworkX MultiGraph**.

## Workflow

1. **Register a project** — give it a name + bounding box (or nominatim address).
2. **Start the pipeline** — this runs four stages asynchronously:

   | Stage | What happens |
   |-------|-------------|
   | *generate* | Downloads slippy-map tiles, stitches them |
   | *infer* | Runs HRNet+OCRNet semantic segmentation |
   | *postprocess* | Cleans polygons, fills gaps with OSM data, estimates widths, builds the graph |
   | *persist* | Writes polygons, network, and graph to DuckDB |

3. **Query results** — polygons and network edges as GeoJSON (with bbox / f_type filters),
   graph summary, or graph edges as GeoJSON.

## Quick start

```bash
# Register a city
curl -X POST http://localhost:8000/projects/  \
  -H "Content-Type: application/json"          \
  -d '{"name":"valencia_centre","location":"39.469,-0.381,39.478,-0.369"}'

# Run the pipeline (async)
curl -X POST http://localhost:8000/projects/valencia_centre/pipeline

# Check progress
curl http://localhost:8000/projects/valencia_centre/pipeline/status

# Get sidewalk polygons as GeoJSON
curl "http://localhost:8000/projects/valencia_centre/polygons?f_type=sidewalk&limit=10"
```

## CRS convention

- Input bounding boxes are WGS84 (EPSG:4326).
- Post-processing runs in a configurable **metric CRS** (default `EPSG:25830` for Valencia).
- Geometries stored in DuckDB are WGS84 — API responses always return WGS84 GeoJSON.
- Edge lengths are reported in **metres** (metric CRS).

## Concurrency

The API uses a single worker by default. DuckDB supports concurrent readers but only one
writer at a time. The registry DuckDB is lightly written (create/delete project, pipeline
status updates), and per-project data DuckDBs are written only during the pipeline.
"""

tags_metadata = [
    {
        "name": "Health",
        "description": "Liveness check.",
    },
    {
        "name": "Projects",
        "description": "Create, list, inspect, update and delete city **projects**.",
    },
    {
        "name": "Pipeline",
        "description": (
            "Start, monitor and cancel the async **pipeline** that runs "
            "`generate → infer → postprocess → persist`."
        ),
    },
    {
        "name": "Data",
        "description": (
            "Query the **output** of a completed project — polygons, network, "
            "and the weighted pedestrian graph."
        ),
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tile2Net API",
        description=DESCRIPTION,
        version="0.4.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=tags_metadata,
        contact={
            "name": "Tile2Net",
            "url": "https://github.com/VIDA-NYU/tile2net",
        },
        license_info={
            "name": "MIT",
            "url": "https://github.com/VIDA-NYU/tile2net/blob/main/LICENSE",
        },
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects.router, prefix="/projects", tags=["Projects"])
    app.include_router(pipeline.router, prefix="/projects", tags=["Pipeline"])
    app.include_router(data.router, prefix="/projects", tags=["Data"])

    @app.get("/", tags=["Health"])
    async def root():
        """Return ``{"status": "ok"}`` if the API is reachable."""
        return {"status": "ok", "version": "0.4.0"}

    @app.exception_handler(ProjectNotFoundError)
    async def _project_not_found(_request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(PipelineConflictError)
    async def _pipeline_conflict(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(_request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


def main():
    """CLI entry point for ``tile2net-api``."""
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
