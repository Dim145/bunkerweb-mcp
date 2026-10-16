"""Schemas for plugin management endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field

from .common import ApiResponse


class PluginsResponse(ApiResponse):
    data: list[dict[str, Any]] | None = Field(
        default=None,
        validation_alias=AliasChoices("data", "plugins"),
    )
