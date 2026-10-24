"""Safe one-shot diagnostic for the live, read-only eBay path."""

from __future__ import annotations

import argparse
import json
from typing import Any, Mapping

from .pipeline import run_search


def summarize(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a credential-free live smoke summary."""

    summary: dict[str, Any] = {
        "ok": bool(payload.get("ok")),
        "status": payload.get("status", "unknown"),
        "source": payload.get("source", "unknown"),
        "read_only": payload.get("read_only") is True,
        "recommended_count": len(payload.get("recommended") or []),
        "rejected_count": len(payload.get("rejected") or []),
        "dropped_count": len(payload.get("dropped") or []),
    }
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
    args = parser.parse_args()
    payload = run_search(args.query, fixture_path=None, limit=args.limit)
    print(json.dumps(summarize(payload), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
