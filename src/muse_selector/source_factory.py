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

    connector_kwargs: dict[str, object] = {"fixture_path": fixture_path}
    if environment is not None:
        connector_kwargs["environment"] = environment
    return EbayBrowseConnector(**connector_kwargs)


__all__ = ["build_source_connector"]
