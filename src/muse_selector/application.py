"""Application use cases shared by CLI, Web, diagnostics and watches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from . import pipeline
from .ports import SourceConnector, SourceConnectorFactory
from .query_parser import PolicyBlockedError, has_explicit_unbounded_budget, parse_query
from .source_factory import build_source_connector


@dataclass(frozen=True)
class SearchApplication:
    """Search use case with an optional injected read-only source connector."""

    connector: SourceConnector | None = None
    source_factory: SourceConnectorFactory = build_source_connector

    def search(
        self,
        query: str,
        fixture_path: str | Path | None = None,
        *,
        limit: int = 10,
        offset: int = 0,
        environment: str | None = None,
        resume_state: Mapping[str, Any] | None = None,
        stage_callback: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        connector = self.connector
        if connector is None and resume_state is None and _query_can_reach_source(query, limit=limit, offset=offset):
            connector = self.source_factory(fixture_path=fixture_path, environment=environment)
        return pipeline.run_search(
            query,
            fixture_path,
            limit=limit,
            offset=offset,
            environment=environment,
            connector=connector,
            resume_state=resume_state,
            stage_callback=stage_callback,
        )


def _query_can_reach_source(query: str, *, limit: int, offset: int) -> bool:
    """Avoid constructing adapters for policy/validation short-circuits."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return False
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return False
    try:
        spec = parse_query(query)
    except (PolicyBlockedError, ValueError):
        return False
    if spec.product_type == "game_account" or spec.region == "CN":
        return False
    return spec.budget_max is not None or has_explicit_unbounded_budget(query)


_DEFAULT_APPLICATION = SearchApplication()


def search(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
    resume_state: Mapping[str, Any] | None = None,
    stage_callback: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the default read-only search application use case."""

    return _DEFAULT_APPLICATION.search(
        query,
        fixture_path,
        limit=limit,
        offset=offset,
        environment=environment,
        resume_state=resume_state,
        stage_callback=stage_callback,
    )


__all__ = ["SearchApplication", "search"]
