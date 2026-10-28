"""Offline shadow evaluation for the HK compatibility and CN local paths."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from muse_selector.connectors.local_fixture import LocalFixtureConnector  # noqa: E402
from muse_selector.persistence import watch_content_fingerprint  # noqa: E402
from muse_selector.pipeline import run_search  # noqa: E402


SHADOW_SCHEMA_VERSION = "muse.selector.shadow.v1"
HK_FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"
CN_FIXTURE = ROOT / "tests" / "fixtures" / "domestic_cn_sample.json"


def _case(
    name: str,
    query: str,
    runner: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    first = runner()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    replay = runner()
    first_ids = [str(item.get("listing_id")) for item in first.get("recommended") or []]
    replay_ids = [str(item.get("listing_id")) for item in replay.get("recommended") or []]
    violations = [
        item.get("listing_id")
        for item in first.get("recommended") or []
        if set(item.get("risk_flags") or ()) & {"evidence_conflict_or_stale", "risk_flagged"}
    ]
    return {
        "name": name,
        "query": query,
        "source": first.get("source"),
        "region": (first.get("search_spec") or {}).get("region"),
        "currency": (first.get("search_spec") or {}).get("currency"),
        "status": first.get("status"),
        "ok": first.get("ok") is True and replay.get("ok") is True,
        "recommended_ids": first_ids,
        "replay_stable": watch_content_fingerprint(first) == watch_content_fingerprint(replay),
        "recommended_order_stable": first_ids == replay_ids,
        "hard_constraint_violations": violations,
        "latency_ms": round(elapsed_ms, 3),
        "read_only": first.get("read_only") is True and replay.get("read_only") is True,
    }


def run_shadow() -> dict[str, Any]:
    cases = [
        _case(
            "hk_compatibility_fixture",
            "香港预算 HKD 7000 以内的迷你主机",
            lambda: run_search("香港预算 HKD 7000 以内的迷你主机", HK_FIXTURE),
        ),
        _case(
            "cn_local_fixture",
            "国内预算 CNY 8000 以内的二手迷你主机",
            lambda: run_search(
                "国内预算 CNY 8000 以内的二手迷你主机",
                connector=LocalFixtureConnector(CN_FIXTURE),
            ),
        ),
    ]
    violations = sum(len(case["hard_constraint_violations"]) for case in cases)
    replay_mismatches = sum(not case["replay_stable"] for case in cases)
    failures = sum(not case["ok"] or not case["read_only"] for case in cases)
    return {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "ok": failures == 0 and violations == 0 and replay_mismatches == 0,
        "read_only": True,
        "mode": "offline_cross_market_shadow",
        "workload_count": len(cases),
        "success_count": len(cases) - failures,
        "failure_count": failures,
        "success_rate": round((len(cases) - failures) / len(cases), 4) if cases else 0.0,
        "hard_constraint_violation_rate": round(violations / len(cases), 4) if cases else 0.0,
        "replay_mismatch_count": replay_mismatches,
        "replay_stability_rate": round(1 - replay_mismatches / len(cases), 4) if cases else 1.0,
        "cost_proxy": {"external_requests": 0, "unit": "local_fixture_pipeline_invocation"},
        "cases": cases,
    }


if __name__ == "__main__":
    report = run_shadow()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if report["ok"] else 1)
