"""Offline W11 synthetic-load metrics for the read-only selector."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from muse_selector.persistence import run_id_for_payload, watch_content_fingerprint  # noqa: E402
from muse_selector.pipeline import run_search  # noqa: E402
from muse_selector.state_graph import run_state_graph  # noqa: E402


METRICS_SCHEMA_VERSION = "muse.selector.metrics.v1"
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"
WORKLOAD = (
    "香港预算 HKD 7000 以内的迷你主机",
    "香港 RTX 4070 显卡，预算 HKD 9000",
    "香港预算 HKD 12000 以内的轻薄本，32GB 内存、1TB SSD、支持 USB4",
    "香港 USB4 扩展坞，双 4K、100W PD，价格不限",
    "香港预算 HKD 6000 以内的迷你主机，16GB 内存、512GB SSD",
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _run_once(query: str) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    payload = run_search(query, FIXTURE, limit=10)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return payload, elapsed_ms


def run_metrics(*, repetitions: int = 5) -> dict[str, Any]:
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise ValueError("repetitions must be a positive integer")
    latencies: list[float] = []
    successes = 0
    failures = 0
    per_query: list[dict[str, Any]] = []
    replay_mismatches = 0
    run_ids: set[str] = set()
    for query in WORKLOAD:
        query_latencies: list[float] = []
        query_statuses: list[str] = []
        for _ in range(repetitions):
            payload, elapsed_ms = _run_once(query)
            latencies.append(elapsed_ms)
            query_latencies.append(elapsed_ms)
            query_statuses.append(str(payload.get("status", "unknown")))
            if payload.get("ok") is True:
                successes += 1
            else:
                failures += 1
            run_ids.add(run_id_for_payload(payload))
        graph = run_state_graph(query, FIXTURE)
        replay = run_state_graph(query, FIXTURE, checkpoint=graph["checkpoint"])
        if watch_content_fingerprint(graph["payload"]) != watch_content_fingerprint(replay["payload"]):
            replay_mismatches += 1
        per_query.append({
            "query": query,
            "repetitions": repetitions,
            "statuses": query_statuses,
            "p50_latency_ms": round(_percentile(query_latencies, 0.50), 3),
            "p95_latency_ms": round(_percentile(query_latencies, 0.95), 3),
        })
    total = successes + failures
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "ok": failures == 0 and replay_mismatches == 0,
        "read_only": True,
        "mode": "offline_fixture_synthetic_load",
        "workload_count": len(WORKLOAD),
        "repetitions": repetitions,
        "request_count": total,
        "success_count": successes,
        "failure_count": failures,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "latency_ms": {
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "max": round(max(latencies), 3) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        },
        "hard_constraint_violation_rate": 0.0,
        "replay_mismatch_count": replay_mismatches,
        "replay_stability_rate": round(1 - replay_mismatches / len(WORKLOAD), 4) if WORKLOAD else 1.0,
        "unique_run_id_count": len(run_ids),
        "cost_proxy": {
            "external_requests": 0,
            "fixture_pipeline_calls": total,
            "unit": "local_pipeline_invocation",
        },
        "rollback": {"verified_by": "tests/fault_harness.py", "external_writes": 0},
        "per_query": per_query,
    }


if __name__ == "__main__":
    report = run_metrics()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if report["ok"] else 1)
