"""Narrow application ports implemented by external adapters and storage."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class SourceConnector(Protocol):
    """Read-only source boundary used by the search application."""

    source_id: str

    @property
    def source_metadata(self) -> Mapping[str, Any]:
        ...

    def search(self, search_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
        ...


class WatchStore(Protocol):
    """Persistence boundary for watch state and replay."""

    def get_watch(self, watch_id: str) -> dict[str, Any] | None:
        ...

    def replay_watch(self, watch_id: str) -> dict[str, Any]:
        ...


__all__ = ["SourceConnector", "WatchStore"]
