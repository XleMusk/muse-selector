"""One-shot read-only smoke command for the official Zhuanzhuan MCP tools."""

from __future__ import annotations

import argparse
import json

from .connectors.zhuanzhuan import ConnectorUnavailable, ZhuanzhuanMcpConnector
from .contracts import ZHUANZHUAN_SMOKE_SCHEMA_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Zhuanzhuan MCP valuation smoke")
    parser.add_argument("--query", required=True, help="product description, model, condition, and other details")
    parser.add_argument("--image-url", action="append", default=[], help="public HTTP(S) image URL; repeat up to 35 times")
    parser.add_argument("--open-entry", action="store_true", help="open a user-facing recycle handoff after valuation")
    args = parser.parse_args()
    connector = ZhuanzhuanMcpConnector()
    try:
        result = connector.recycle_valuation(args.query, image_urls=args.image_url)
        if args.open_entry and result.get("handoff"):
            handoff = result["handoff"]
            result["entry"] = connector.open_recycle_entry(
                query=args.query,
                model_id=handoff.get("model_id") if isinstance(handoff, dict) else None,
            )
    except (ConnectorUnavailable, ValueError) as exc:
        result = {
            "schema_version": ZHUANZHUAN_SMOKE_SCHEMA_VERSION,
            "source_id": connector.source_id,
            "capability": "recycle_valuation",
            "ok": False,
            "status": "source_unavailable",
            "message": str(exc),
            "read_only": True,
        }
    else:
        result = {"schema_version": ZHUANZHUAN_SMOKE_SCHEMA_VERSION, **result}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

