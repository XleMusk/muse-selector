"""Safe one-shot diagnostic for the live, read-only eBay path."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Mapping

from .connectors.ebay import _allowed_pagination_url
from .contracts import RESULT_SCHEMA_VERSION
from .pipeline import run_search


def _safe_source_metadata(value: Any) -> dict[str, Any] | None:
    """Keep only bounded Browse page metadata in the credential-free report."""

    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for field in ("href", "next", "prev"):
        item = value.get(field)
        if _allowed_pagination_url(item):
            result[field] = item
        else:
            result[field] = None
    for field in ("total", "limit", "offset"):
        item = value.get(field)
        result[field] = item if isinstance(item, int) and not isinstance(item, bool) else None
    environment = value.get("environment")
    result["environment"] = environment if environment in {"production", "sandbox"} else "unknown"
    return result


def summarize(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a credential-free live smoke summary."""

    summary: dict[str, Any] = {
        "schema_version": payload.get("schema_version", RESULT_SCHEMA_VERSION),
        "ok": bool(payload.get("ok")),
        "status": payload.get("status", "unknown"),
        "source": payload.get("source", "unknown"),
        "read_only": payload.get("read_only") is True,
        "recommended_count": len(payload.get("recommended") or []),
        "rejected_count": len(payload.get("rejected") or []),
        "dropped_count": len(payload.get("dropped") or []),
        "source_metadata": _safe_source_metadata(payload.get("source_metadata")),
    }
    credential_count = sum(bool(os.getenv(name)) for name in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"))
    summary["credential_state"] = {0: "missing", 1: "partial", 2: "present"}[credential_count]
    if payload.get("ok"):
        observed = {
            str(item.get("observed_at"))
            for card in payload.get("recommended") or []
            for item in card.get("evidence") or []
            if item.get("observed_at")
        }
        summary["observed_at_samples"] = sorted(observed)[:5]
    else:
        summary["message"] = payload.get("message", "")
        if payload.get("ask"):
            summary["ask"] = list(payload["ask"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot live read-only eBay smoke check")
    parser.add_argument("--query", required=True, help="explicit Hong Kong hardware query with a budget")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0, help="single Browse page offset; no automatic pagination")
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    args = parser.parse_args()
    previous_environment = os.environ.get("EBAY_ENVIRONMENT")
    try:
        if args.environment is not None:
            os.environ["EBAY_ENVIRONMENT"] = args.environment
        payload = run_search(args.query, fixture_path=None, limit=args.limit, offset=args.offset)
    finally:
        if previous_environment is None:
            os.environ.pop("EBAY_ENVIRONMENT", None)
        else:
            os.environ["EBAY_ENVIRONMENT"] = previous_environment
    print(json.dumps(summarize(payload), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
