"""Shared filter result model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FilterResult:
    """Result of applying one signal filter."""

    passed: bool
    reason: str | None = None
    confidence_multiplier: float = 1.0
