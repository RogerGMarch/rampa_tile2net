"""Custom exceptions for the Tile2Net API."""
from __future__ import annotations


class ProjectNotFoundError(ValueError):
    """Raised when a project name is not found in the registry."""


class PipelineConflictError(RuntimeError):
    """Raised when a pipeline is already running for a project."""
