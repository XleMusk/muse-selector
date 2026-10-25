"""Offline installation and fixture diagnostics for Muse Selector.

The doctor command deliberately never contacts a marketplace.  It verifies the
local Python/package setup and, when a fixture is supplied, exercises the same
read-only pipeline used by the CLI.  Credential checks report presence only;
secret values are never included in the result.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from .pipeline import run_search


DEFAULT_QUERY = "香港预算 HKD 7000 以内的迷你主机"


def _check(name: str, ok: bool, detail: str, *, skipped: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "ok": bool(ok), "detail": detail}
    if skipped:
        result["skipped"] = True
    return result


def _credential_state() -> dict[str, str]:
    def state(*names: str) -> str:
        present = sum(bool(os.getenv(name)) for name in names)
        return {0: "missing", 1: "partial", 2: "present"}[present]

    return {
        "ebay": state("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"),
        "zhuanzhuan": "present" if bool(os.getenv("ZHUANZHUAN_MCP_TOKEN")) else "missing",
    }


def run_doctor(
    fixture_path: str | Path | None = None,
    *,
    query: str = DEFAULT_QUERY,
    limit: int = 10,
) -> dict[str, Any]:
    """Return a deterministic local readiness report.

    A fixture check is optional so an installed package can be diagnosed
    outside a source checkout.  Supplying a fixture validates the full offline
    result contract and catches broken fixture paths or malformed data.
    """

    checks: list[dict[str, Any]] = []
    version = sys.version_info
    python_ok = (version.major, version.minor) >= (3, 10)
    checks.append(_check("python", python_ok, platform.python_version()))

    try:
        import muse_selector  # noqa: F401  # local import is the check itself

        checks.append(_check("package_import", True, "muse_selector import ok"))
    except Exception as exc:  # pragma: no cover - import failures are environment-specific
        checks.append(_check("package_import", False, f"{type(exc).__name__}: {exc}"))

    if fixture_path is None:
        checks.append(_check("fixture_pipeline", True, "no fixture supplied", skipped=True))
    else:
        path = Path(fixture_path)
        if not path.is_file():
            checks.append(_check("fixture_pipeline", False, f"fixture not found: {path}"))
        elif isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            checks.append(_check("fixture_pipeline", False, "limit must be a positive integer"))
        else:
            try:
                payload = run_search(query, path, limit=limit)
                cards = payload.get("recommended") or []
                coverage_ok = all(float(card.get("evidence_coverage", 0)) >= 0.95 for card in cards)
                pipeline_ok = (
                    payload.get("ok") is True
                    and payload.get("read_only") is True
                    and isinstance(cards, list)
                    and bool(cards)
                    and coverage_ok
                )
                detail = f"{len(cards)} recommended card(s); status={payload.get('status', 'unknown')}"
                checks.append(_check("fixture_pipeline", pipeline_ok, detail))
            except Exception as exc:  # malformed fixture should be reported, not hidden
                checks.append(_check("fixture_pipeline", False, f"{type(exc).__name__}: {exc}"))

    ok = all(item["ok"] for item in checks if not item.get("skipped"))
    return {
        "ok": ok,
        "status": "healthy" if ok else "unhealthy",
        "read_only": True,
        "checks": checks,
        "credential_state": _credential_state(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Muse Selector installation and fixture diagnostics")
    parser.add_argument("--fixture", default=None, help="optional offline eBay fixture to validate")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="query used for the optional fixture check")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    report = run_doctor(args.fixture, query=args.query, limit=args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
