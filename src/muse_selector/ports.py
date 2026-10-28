"""Narrow application ports implemented by external adapters and storage."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol


class SourceConnector(Protocol):
    """Read-only source boundary used by the search application."""

    source_id: str

    @property
    def source_metadata(self) -> Mapping[str, Any]:
        ...

    def search(self, search_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
        ...


class SourceConnectorFactory(Protocol):
    """Composition-root boundary for constructing a source connector."""

    def __call__(
        self,
        *,
        fixture_path: str | Path | None = None,
        environment: str | None = None,
    ) -> SourceConnector:
        ...


class WatchStore(Protocol):
    """Persistence boundary for watch state and replay."""

    def get_watch(self, watch_id: str) -> dict[str, Any] | None:
        ...

    def replay_watch(self, watch_id: str) -> dict[str, Any]:
        ...


class Clock(Protocol):
    """Explicit time dependency for deterministic application logic."""

    def now(self) -> datetime:
        ...


__all__ = ["Clock", "SourceConnector", "SourceConnectorFactory", "WatchStore"]
