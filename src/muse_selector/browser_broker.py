"""Feature-gated, read-only browser broker contract.

The first browser milestone is intentionally an adapter boundary.  It can read
an accessibility tree from a test adapter, but it never owns credentials and
does not expose click, type, JavaScript or navigation-write operations.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlparse


BROWSER_SCHEMA_VERSION = "muse.selector.browser.v1"
ALLOWED_HOSTS = frozenset({"ebay.com.hk", "www.ebay.com.hk"})
_SENSITIVE_KEYS = frozenset({
    "access_token", "authorization", "client_secret", "cookie", "credential",
    "credentials", "password", "passwd", "secret", "set-cookie", "token",
})


def _feature_enabled() -> bool:
    return os.getenv("MUSE_READONLY_BROWSER_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("browser URL contains invalid control characters")
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("browser URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("browser URL is outside the official eBay HK read-only allowlist")
    sensitive_query_keys = {"access_token", "authorization", "client_secret", "cookie", "password", "secret", "token"}
    if any(str(key).strip().casefold() in sensitive_query_keys for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise ValueError("browser URL contains a credential-like query parameter")
    return value


def _sanitize(value: Any, *, depth: int = 0) -> tuple[Any, int]:
    """Remove credential-like keys from an adapter tree without executing it."""

    if depth > 20:
        return "[depth-limited]", 0
    if isinstance(value, Mapping):
        mapping_result: dict[str, Any] = {}
        redacted = 0
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.strip().casefold() in _SENSITIVE_KEYS:
                redacted += 1
                continue
            clean_value, count = _sanitize(raw_value, depth=depth + 1)
            mapping_result[key] = clean_value
            redacted += count
        return mapping_result, redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sequence_result: list[Any] = []
        redacted = 0
        for item in value:
            clean_value, count = _sanitize(item, depth=depth + 1)
            sequence_result.append(clean_value)
            redacted += count
        return sequence_result, redacted
    return value, 0


class ReadOnlyBrowserBroker:
    """Read-only accessibility-tree broker with an injected adapter boundary."""

    def __init__(self, adapter: Any | None = None, *, enabled: bool | None = None) -> None:
        self.adapter = adapter
        self.enabled = _feature_enabled() if enabled is None else bool(enabled)

    @staticmethod
    def manual_handoff(url: str) -> dict[str, Any]:
        safe = _safe_url(url)
        return {"action": "user_open", "url": safe, "read_only": True}

    def snapshot(self, url: str) -> dict[str, Any]:
        try:
            safe = _safe_url(url)
        except ValueError as exc:
            return {
                "schema_version": BROWSER_SCHEMA_VERSION,
                "ok": False,
                "status": "invalid_url",
                "message": str(exc),
                "read_only": True,
            }
        handoff = {"action": "user_open", "url": safe, "read_only": True}
        if not self.enabled:
            return {
                "schema_version": BROWSER_SCHEMA_VERSION,
                "ok": False,
                "status": "feature_disabled",
                "read_only": True,
                "manual_handoff": handoff,
            }
        reader = getattr(self.adapter, "read_accessibility_tree", None)
        if not callable(reader):
            return {
                "schema_version": BROWSER_SCHEMA_VERSION,
                "ok": False,
                "status": "broker_unavailable",
                "read_only": True,
                "manual_handoff": handoff,
            }
        try:
            tree = reader(safe)
            clean_tree, redacted_count = _sanitize(tree)
        except (OSError, RuntimeError, TypeError, ValueError):
            return {
                "schema_version": BROWSER_SCHEMA_VERSION,
                "ok": False,
                "status": "browser_unavailable",
                "read_only": True,
                "manual_handoff": handoff,
            }
        return {
            "schema_version": BROWSER_SCHEMA_VERSION,
            "ok": True,
            "status": "tree_ready",
            "read_only": True,
            "url": safe,
            "tree": clean_tree,
            "redacted_field_count": redacted_count,
            "manual_handoff": handoff,
        }


__all__ = ["ALLOWED_HOSTS", "BROWSER_SCHEMA_VERSION", "ReadOnlyBrowserBroker"]
