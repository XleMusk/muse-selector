"""Application use cases shared by CLI, Web, diagnostics and watches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import pipeline
from .ports import SourceConnector


@dataclass(frozen=True)
class SearchApplication:
    """Search use case with an optional injected read-only source connector."""

    connector: SourceConnector | None = None

    def search(
        self,
        query: str,
        fixture_path: str | Path | None = None,
        *,
        limit: int = 10,
        offset: int = 0,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return pipeline.run_search(
            query,
            fixture_path,
            limit=limit,
            offset=offset,
            environment=environment,
            connector=self.connector,
        )


_DEFAULT_APPLICATION = SearchApplication()


def search(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
) -> dict[str, Any]:
    """Run the default read-only search application use case."""

    return _DEFAULT_APPLICATION.search(
        query,
        fixture_path,
        limit=limit,
        offset=offset,
        environment=environment,
    )


__all__ = ["SearchApplication", "search"]
