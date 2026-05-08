"""API-level configuration — paths, defaults, env-var overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ApiConfig:
    data_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("TILE2NET_HOME", Path.home() / ".tile2net")
        )
    )
    registry_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("TILE2NET_REGISTRY", Path.home() / ".tile2net" / "registry.db")
        )
    )
    default_metric_crs: str = "EPSG:25830"
    max_task_age_hours: int = 24
    log_level: str = "info"


_config: ApiConfig | None = None


def get_api_config() -> ApiConfig:
    global _config
    if _config is None:
        _config = ApiConfig()
    return _config
