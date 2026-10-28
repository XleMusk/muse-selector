"""Composition-root factories for external source connectors."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .connectors.ebay import EbayBrowseConnector, credential_env_names, credential_state
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


def describe_default_source(environment: str | None = None) -> dict[str, Any]:
    """Describe the default read-only source without making a network call."""

    selected = str(environment if environment is not None else os.environ.get("EBAY_ENVIRONMENT", "production")).strip().lower()
    valid = selected in {"production", "sandbox"}
    description: dict[str, Any] = {
        "environment": selected if valid else "unknown",
        "credential_state": credential_state(selected) if valid else "missing",
        "api_host": None,
        "token_path": None,
        "credential_env": None,
        "status": "configuration_error" if not valid else "credential_unavailable",
    }
    if valid:
        client_id_var, client_secret_var = credential_env_names(selected)
        description["credential_env"] = {
            "scoped": [client_id_var, client_secret_var],
            "legacy_fallback": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"],
        }
    try:
        connector = build_source_connector(environment=selected if valid else None)
        config = getattr(connector, "config")
        kill_switch = getattr(connector, "_kill_switch_active", None)
        kill_switch_active = kill_switch() if callable(kill_switch) else False
        live_enabled = getattr(connector, "live_enabled", False)
        description.update(
            {
                "environment": config.environment,
                "credential_state": getattr(connector, "credential_state", description["credential_state"]),
                "api_host": urlparse(config.api_base).hostname,
                "token_path": urlparse(config.token_url).path,
                "credential_env": {
                    "scoped": list(credential_env_names(config.environment)),
                    "legacy_fallback": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"],
                },
                "status": (
                    "disabled"
                    if kill_switch_active
                    else "ready"
                    if live_enabled
                    else "credential_unavailable"
                ),
            }
        )
    except (AttributeError, TypeError, ValueError, OSError):
        pass
    return description


__all__ = ["build_source_connector", "describe_default_source"]
