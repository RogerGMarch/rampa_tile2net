"""Pydantic request/response models for the Tile2Net API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════════
#  Project
# ═══════════════════════════════════════════════════════════════════════════════


class PostProcessConfigCreate(BaseModel):
    """Tunable parameters forwarded to :class:`PostProcessConfig`.

    All distance values are in **metres** and apply in *metric_crs*.
    """

    metric_crs: str = Field(
        "EPSG:25830",
        description="Metric CRS for all spatial operations (UTM Zone 30N for Valencia).",
        examples=["EPSG:25830"],
    )
    simplify_tol: float = Field(
        2.5,
        ge=0,
        description="Simplification tolerance (metres) applied to raw tile2net polygons.",
    )
    buffer_close: float = Field(
        1.2,
        ge=0,
        description="Open/close buffer radius (metres) to seal micro-gaps and remove spurs.",
    )
    min_area: float = Field(
        5.0,
        ge=0,
        description="Minimum polygon area (m²); smaller fragments are dropped.",
    )
    osm_filter_dist: float = Field(
        10.0,
        ge=0,
        description="Drop tile2net polygons further than this from any viario edge (metres).",
    )
    touch_buf: float = Field(
        3.0,
        ge=0,
        description="Primary search radius (metres) for touching-polygon width estimation.",
    )
    fallback_buf: float = Field(
        30.0,
        ge=0,
        description="Wider search radius (metres) when nothing is found within *touch_buf*.",
    )
    fill_cov_max: float = Field(
        0.60,
        ge=0,
        le=1,
        description="Skip gap-fill for an OSM edge already above this coverage fraction.",
    )
    half_w_clamp_lo: float = Field(
        1.2,
        ge=0,
        description="Lower clamp bound for estimated fill half-width (metres).",
    )
    half_w_clamp_hi: float = Field(
        6.0,
        ge=0,
        description="Upper clamp bound for estimated fill half-width (metres).",
    )


class ProjectCreate(BaseModel):
    """Request body to register a new city project."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9_]+$",
        description="Unique project slug (lowercase alphanumeric + underscore).",
        examples=["valencia_rusafa"],
    )
    location: str = Field(
        ...,
        description="Bounding-box as ``S,W,N,E`` decimal degrees, or a nominatim address string.",
        examples=["39.469,-0.381,39.478,-0.369"],
    )
    zoom: int = Field(
        19,
        ge=0,
        le=22,
        description="Slippy-map zoom level for tile download.",
    )
    crs: int = Field(
        4326,
        description="EPSG code of the ``location`` bounding-box coordinates (almost always 4326).",
    )
    metric_crs: str = Field(
        "EPSG:25830",
        description="Metric CRS for post-processing measurements.",
        examples=["EPSG:25830", "EPSG:32630"],
    )
    source: str | None = Field(
        None,
        description="Optional tile source key (see the tile2net source catalogue).",
    )
    tile_step: int = Field(
        1,
        ge=1,
        description="Tile step during generation (default 1).",
    )
    stitch_step: int = Field(
        4,
        ge=1,
        description="Stitch step during generation (default 4).",
    )
    viario_type: Literal["osm", "official"] = Field(
        "osm",
        description="Viario source: ``osm`` uses Overpass API, ``official`` uses a municipal open-data service.",
    )
    viario_url: str | None = Field(
        None,
        description="URL for the official viario source (required when ``viario_type='official'``).",
    )
    postprocess_config: PostProcessConfigCreate | None = Field(
        None,
        description="Optional overrides for post-processing parameters.",
    )


class ProjectPatch(BaseModel):
    """Fields that can be updated after project creation."""

    metric_crs: str | None = Field(
        None,
        description="Change the metric CRS used during post-processing.",
    )
    viario_type: Literal["osm", "official"] | None = Field(
        None,
        description="Change the viario source type.",
    )
    viario_url: str | None = Field(
        None,
        description="Change the official viario URL.",
    )


class PipelineProjectInfo(BaseModel):
    """Nested pipeline status attached to a project response."""

    task_id: str | None = Field(None, description="UUID of the running/completed pipeline task.")
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = Field(
        None, description="Current pipeline lifecycle status."
    )
    stage: Literal["generating", "inferring", "postprocessing"] | None = Field(
        None, description="Current pipeline stage (only meaningful when *status* is 'running')."
    )
    progress: float | None = Field(None, description="Progress 0.0–1.0.")
    message: str | None = Field(None, description="Human-readable status message.")


class ProjectInfo(BaseModel):
    """Complete read-only project view, including optional pipeline status."""

    name: str = Field(..., description="Project slug.", examples=["valencia_rusafa"])
    location: str = Field(..., description="Original location string used at creation.")
    zoom: int = Field(..., description="Tile zoom level.")
    crs: int = Field(..., description="EPSG code of the bbox coordinate system.")
    metric_crs: str = Field(..., description="Metric CRS used for post-processing.")
    viario_type: str = Field(..., description="Viario source type (osm / official).")
    status: Literal[
        "created", "generating", "inferring", "postprocessing", "completed", "failed"
    ] = Field(..., description="Project lifecycle status.")
    bbox_wgs84: list[float] | None = Field(
        None,
        description="Bounding box as ``[S, W, N, E]`` in WGS84 decimal degrees.",
        examples=[[39.469, -0.381, 39.478, -0.369]],
    )
    created_at: datetime | None = Field(None, description="Timestamp when the project was created.")
    updated_at: datetime | None = Field(
        None, description="Timestamp of the last registry update."
    )
    pipeline: PipelineProjectInfo | None = Field(
        None, description="Current pipeline status (only present after at least one run)."
    )


class ProjectList(BaseModel):
    """Wrapper for the list-projects response."""

    projects: list[ProjectInfo]


class ProjectDeleteResponse(BaseModel):
    """Confirmation payload for a successful project deletion."""

    name: str = Field(..., description="The project slug that was deleted.")
    deleted: bool = Field(..., description="Always ``true`` on success.")

# ═══════════════════════════════════════════════════════════════════════════════
#  Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class PipelineTrigger(BaseModel):
    """Optional flags controlling pipeline behaviour."""

    force_reprocess: bool = Field(
        False,
        description="Re-download tiles even if they already exist on disk.",
    )
    skip_generate: bool = Field(
        False,
        description="Skip the tile-download stage (requires a prior successful generate run).",
    )
    skip_postprocess: bool = Field(
        False,
        description="Stop after inference; do not run post-processing or persist to DuckDB.",
    )
    dump_percent: int = Field(
        0,
        ge=0,
        le=100,
        description="Passed through to the inference ``--dump_percent`` flag.",
    )


class PipelineStatus(BaseModel):
    """Complete read-only view of a pipeline run."""

    task_id: str = Field(..., description="UUID of the pipeline task.")
    project_name: str = Field(..., description="Project slug this task belongs to.")
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = Field(
        ..., description="Pipeline lifecycle status."
    )
    stage: Literal["generating", "inferring", "postprocessing"] | None = Field(
        None,
        description=(
            "Current pipeline stage. ``generating`` = tile download + stitch, "
            "``inferring`` = semantic segmentation, "
            "``postprocessing`` = polygon cleaning, gap-fill, graph build + DuckDB persist."
        ),
    )
    progress: float = Field(0.0, description="Progress 0.0–1.0.", ge=0, le=1)
    message: str | None = Field(None, description="Human-readable status message.")
    started_at: datetime | None = Field(
        None, description="Timestamp when the pipeline started."
    )
    finished_at: datetime | None = Field(
        None, description="Timestamp when the pipeline finished (or was cancelled)."
    )
    error: str | None = Field(
        None, description="Traceback string if the pipeline failed."
    )


class PipelineCancelResponse(BaseModel):
    """Confirmation payload when a pipeline is cancelled."""

    task_id: str = Field(..., description="UUID of the cancelled task.")
    cancelled: bool = Field(..., description="Always ``true`` on success.")


# ═══════════════════════════════════════════════════════════════════════════════
#  Data queries
# ═══════════════════════════════════════════════════════════════════════════════


class GraphSummary(BaseModel):
    """Lightweight graph statistics (no geometry)."""

    project_name: str = Field(..., description="Project slug.")
    node_count: int = Field(..., description="Number of graph nodes.")
    edge_count: int = Field(..., description="Number of graph edges.")
    total_length_m: float = Field(
        ..., description="Sum of all edge ``length`` attributes, in metres."
    )
    crs: str = Field(
        ..., description="Metric CRS in which lengths are expressed."
    )
    components: int = Field(..., description="Number of connected components.")
