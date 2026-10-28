"""Composition-root factories for external source connectors."""

from __future__ import annotations

from pathlib import Path

from .connectors.ebay import EbayBrowseConnector
from .ports import SourceConnector


def build_source_connector(
    *,
    fixture_path: str | Path | None = None,
    environment: str | None = None,
) -> SourceConnector:
    """Build the default read-only eBay source adapter."""

    if environment is None:
        return EbayBrowseConnector(fixture_path=fixture_path)
    return EbayBrowseConnector(fixture_path=fixture_path, environment=environment)


__all__ = ["build_source_connector"]
