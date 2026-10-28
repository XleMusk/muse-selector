"""Offline regression harness for the Hong Kong computer/hardware MVP.

The harness deliberately consumes JSON fixtures and the deterministic contracts in
``src/muse_selector``. It never calls an external API. A production connector can
reuse the same normalized Listing/Evidence objects and run this suite before merge.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from muse_selector.contracts import Evidence, Listing, SearchSpec  # noqa: E402
from muse_selector.feedback_contracts import load_feedback_fixture, replay_feedback  # noqa: E402
from muse_selector.filtering import filter_listings  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
IDENTITY_KEY_PRIORITY = ("gtin", "epid", "mpn", "sku")


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def load_queries() -> list[dict[str, Any]]:
    return load_json("queries.json")


def load_raw_listings() -> list[dict[str, Any]]:
    return load_json("listings.json")


def build_spec(case: dict[str, Any]) -> SearchSpec:
    constraints = dict(case.get("hard_constraints") or {})
    # Fixture names are human-readable; contracts use the concrete listing key
    # and the deterministic matcher treats numeric requirements as minimums.
    key_map = {
        "ram_gb_min": "ram_gb",
        "storage_gb_min": "storage_gb",
        "vram_gb_min": "vram_gb",
        "display_4k_count_min": "display_4k_count",
        "pd_watt_min": "pd_watt",
        "usb4_required": "usb4",
    }
    return SearchSpec(
        query=case["query"],
        required_specs={key_map.get(k, k): v for k, v in constraints.items() if k not in {"max_total_hkd", "shipping_included"}},
        budget_max=constraints.get("max_total_hkd"),
        region=case.get("location") or "HK",
        currency=case.get("currency") or "HKD",
        condition="unknown" if case["case_id"] == "missing_budget" else "new",
    )


def _status_flags(raw: dict[str, Any]) -> tuple[str, ...]:
    flags: list[str] = []
    risk = str(raw.get("risk") or "").upper()
    if risk == "BLOCKED":
        flags.append("policy_blocked")
    if risk == "HIGH":
        flags.append("high_risk")
    for ev in raw.get("evidence") or []:
        status = ev.get("status")
        if status in {"stale", "conflict"}:
            flags.append(status)
    return tuple(sorted(set(flags)))


def build_listing(raw: dict[str, Any]) -> Listing:
    source = raw["source"]
    price = raw.get("price") or {}
    return Listing(
        listing_id=raw["listing_id"],
        source_id=source["source_id"],
        title=raw["title"],
        url=source["url"],
        region=raw.get("region") or "HK",
        currency=(price.get("currency") or "HKD"),
        price=price.get("amount"),
        shipping_cost=price.get("shipping"),
        tax=price.get("tax"),
        stock_status={"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock"}.get(
            raw.get("availability"), "unknown"
        ),
        condition={"NEW": "new", "USED": "used", "REFURBISHED": "refurbished"}.get(
            raw.get("condition"), "unknown"
        ),
        specs=raw.get("specs") or {},
        evidence_ids=tuple(f"{raw['listing_id']}:{i}" for i, _ in enumerate(raw.get("evidence") or [])),
        source_observed_at=source.get("observed_at") or "",
        risk_flags=_status_flags(raw),
    )


def build_evidence(raw: dict[str, Any]) -> list[Evidence]:
    source = raw["source"]
    out: list[Evidence] = []
    for i, ev in enumerate(raw.get("evidence") or []):
        out.append(
            Evidence(
                evidence_id=f"{raw['listing_id']}:{i}",
                source_id=source["source_id"],
                source_url=ev.get("source_url") or source["url"],
                field=ev["field"],
                value=ev.get("value"),
                observed_at=ev.get("observed_at") or source.get("observed_at"),
                status=ev.get("status") or "unknown",
            )
        )
    return out


def is_blocked_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://169.254.169.254", "http://127.0.0.1", "http://localhost"))


def canonical_ids(listings: Iterable[Listing]) -> list[str]:
    return sorted(item.listing_id for item in listings)


def _ranking_metrics(predicted_ids: list[str], relevant_ids: Iterable[str], k: int) -> dict[str, float]:
    """Return bounded offline ranking metrics for a labeled fixture case.

    Precision uses the conventional ``k`` denominator, so missing results in
    the top-k window count as non-relevant.  The fixture is small, but keeping
    the calculation explicit makes the baseline reusable for larger snapshots.
    """

    relevant = set(relevant_ids)
    top_ids = predicted_ids[:k]
    hits = sum(1 for listing_id in top_ids if listing_id in relevant)
    precision = hits / k if k else 0.0
    recall = hits / len(relevant) if relevant else 0.0
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, listing_id in enumerate(top_ids)
        if listing_id in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    ndcg = dcg / idcg if idcg else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "ndcg": ndcg,
    }


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _quality_text(value: Any) -> str | None:
    """Normalize an explicitly supplied identity value without inferring it."""

    if value in (None, "") or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text.casefold() if text else None


def _identity_key(raw: dict[str, Any]) -> str | None:
    """Choose a deterministic identity key from source-provided fields only."""

    specs = raw.get("specs") if isinstance(raw.get("specs"), dict) else {}
    for field in IDENTITY_KEY_PRIORITY:
        value = _quality_text(raw.get(field)) or _quality_text(specs.get(field))
        if value is not None:
            return f"{field}:{value}"
    brand = _quality_text(raw.get("brand")) or _quality_text(specs.get("brand"))
    model = _quality_text(raw.get("model")) or _quality_text(specs.get("model"))
    if brand is not None and model is not None:
        return f"brand_model:{brand}|{model}"
    return None


def _observed_at(raw: dict[str, Any]) -> datetime | None:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    value = source.get("observed_at") or raw.get("source_observed_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        observed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed


def build_quality_report(raw_listings: Iterable[dict[str, Any]], *, ttl_hours: int = 72) -> dict[str, Any]:
    """Build deterministic entity and freshness metrics from source fields."""

    rows = [item for item in raw_listings if isinstance(item, dict)]
    keys: dict[str, list[str]] = {}
    observed: dict[str, datetime | None] = {}
    for raw in rows:
        listing_id = str(raw.get("listing_id") or "unknown")
        key = _identity_key(raw)
        if key is not None:
            keys.setdefault(key, []).append(listing_id)
        observed[listing_id] = _observed_at(raw)
    valid_times = [item for item in observed.values() if item is not None]
    reference = max(valid_times) if valid_times else None
    stale_count = 0
    fresh_count = 0
    unknown_observed_at_count = 0
    for value in observed.values():
        if value is None or reference is None:
            unknown_observed_at_count += 1
            continue
        if (reference - value).total_seconds() > ttl_hours * 3600:
            stale_count += 1
        else:
            fresh_count += 1
    duplicate_groups = {key: ids for key, ids in keys.items() if len(ids) > 1}
    known_count = sum(len(ids) for ids in keys.values())
    return {
        "listing_count": len(rows),
        "identity_key_priority": list(IDENTITY_KEY_PRIORITY) + ["brand_model"],
        "identity_key_count": len(keys),
        "identity_unknown_count": len(rows) - known_count,
        "identity_coverage_rate": round(known_count / len(rows), 4) if rows else 0.0,
        "identity_key_counts": {key: len(ids) for key, ids in sorted(keys.items())},
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_listing_count": sum(len(ids) - 1 for ids in duplicate_groups.values()),
        "duplicate_groups": {key: sorted(ids) for key, ids in sorted(duplicate_groups.items())},
        "ttl_hours": ttl_hours,
        "reference_at": reference.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if reference else None,
        "fresh_count": fresh_count,
        "stale_count": stale_count,
        "unknown_observed_at_count": unknown_observed_at_count,
    }


def validate_fixture_shape() -> list[str]:
    policy = load_json("regression_policy.json")
    errors: list[str] = []
    required = set(policy["required_evidence_fields"])
    for raw in load_raw_listings():
        for ev in raw.get("evidence") or []:
            missing = sorted(required - set(ev))
            if missing:
                errors.append(f"{raw['listing_id']}: evidence missing {missing}")
        if raw.get("category") == "game_account" and raw.get("risk") != "BLOCKED":
            errors.append(f"{raw['listing_id']}: game account must be BLOCKED")
        if is_blocked_url(raw["source"]["url"]):
            errors.append(f"{raw['listing_id']}: SSRF URL was admitted")
    return errors


def run_regression() -> dict[str, Any]:
    errors = validate_fixture_shape()
    feedback_records = load_feedback_fixture(str(FIXTURES / "feedback_events.json"))
    raw = load_raw_listings()
    hardware_raw = [item for item in raw if item.get("category") != "game_account"]
    listings = [build_listing(item) for item in hardware_raw]
    policy = load_json("regression_policy.json")
    quality_report = build_quality_report(
        hardware_raw,
        ttl_hours=int(policy.get("freshness_ttl_hours", 72)),
    )
    query_results: dict[str, Any] = {}
    accepted_total = 0
    accepted_violations = 0
    labeled_metrics: list[dict[str, float]] = []
    replay_jaccards: list[float] = []
    recommendations_by_run: dict[str, list[str]] = {}

    for case in load_queries():
        case_id = case["case_id"]
        expected = case["expected"]
        if case_id == "missing_budget":
            if not expected.get("must_ask"):
                errors.append("missing_budget: expected clarification fields")
            query_results[case_id] = {"accepted": [], "ask": expected["must_ask"]}
            continue
        if case_id == "ssrf_url":
            if not is_blocked_url("http://169.254.169.254/latest/meta-data/"):
                errors.append("ssrf_url: metadata endpoint was not blocked")
            query_results[case_id] = {"accepted": [], "blocked": True}
            continue
        if case_id == "game_account_policy_block":
            if any(item.get("risk") != "BLOCKED" for item in raw if item.get("category") == "game_account"):
                errors.append("game_account_policy_block: policy did not block account listing")
            query_results[case_id] = {"accepted": [], "policy_blocked": True}
            continue

        spec = build_spec(case)
        accepted, decisions = filter_listings(spec, listings)
        ids = canonical_ids(accepted)
        ranked_ids = [item.listing_id for item in accepted]
        recommendations_by_run[f"regression:{case_id}"] = ranked_ids
        query_results[case_id] = {"accepted": ids, "decisions": [asdict(d) for d in decisions]}
        if expected.get("must_return") and not accepted:
            errors.append(f"{case_id}: expected at least one accepted listing")
        if expected.get("replay_must_be_stable"):
            accepted_again, _ = filter_listings(spec, listings)
            if ids != canonical_ids(accepted_again):
                errors.append(f"{case_id}: replay ordering changed")
        accepted_again, _ = filter_listings(spec, listings)
        replay_ranked_ids = [item.listing_id for item in accepted_again]
        top_k_jaccard = _jaccard(ranked_ids[:10], replay_ranked_ids[:10])
        query_results[case_id]["top_k_jaccard"] = top_k_jaccard
        relevant_ids = expected.get("relevant_listing_ids")
        if relevant_ids is not None:
            relevant_ids = [str(item) for item in relevant_ids]
            known_ids = {item.listing_id for item in listings}
            unknown_relevant = sorted(set(relevant_ids) - known_ids)
            if unknown_relevant:
                errors.append(f"{case_id}: relevant fixture ids are unknown: {unknown_relevant}")
            metrics_at_10 = _ranking_metrics(ranked_ids, relevant_ids, 10)
            metrics_at_20 = _ranking_metrics(ranked_ids, relevant_ids, 20)
            query_results[case_id]["ranking_metrics"] = {
                "precision_at_10": metrics_at_10["precision"],
                "recall_at_20": metrics_at_20["recall"],
                "ndcg_at_10": metrics_at_10["ndcg"],
            }
            labeled_metrics.append(query_results[case_id]["ranking_metrics"])
            replay_jaccards.append(top_k_jaccard)
        for item in accepted:
            accepted_total += 1
            decision = next(item_decision for item_decision in decisions if item_decision.listing_id == item.listing_id)
            if decision.reasons:
                accepted_violations += 1
                errors.append(f"{case_id}: accepted listing violated hard constraints: {item.listing_id}")
            if "stale" in item.risk_flags or "conflict" in item.risk_flags:
                errors.append(f"{case_id}: stale/conflict listing was recommended: {item.listing_id}")
            if item.landed_cost is None and spec.budget_max is not None:
                errors.append(f"{case_id}: unknown total cost passed a budget constraint")

        if case_id == "conflict_shipping":
            # A conflict must be visible in the result set even when a different
            # fully evidenced listing is accepted for recommendation.
            raw_conflict = next(item for item in raw if item["listing_id"] == "ebay-hk-conflict-001")
            if raw_conflict["evidence"][0]["status"] != "conflict":
                errors.append("conflict_shipping: conflict was hidden")

    # Unknown and conflict values must remain unknown; no implicit total is computed.
    conflict = next(item for item in raw if item["listing_id"] == "ebay-hk-conflict-001")
    if conflict["price"]["total"] is not None:
        errors.append("conflict fixture: total must remain unknown")
    if conflict["evidence"][0]["status"] != "conflict":
        errors.append("conflict fixture: conflict status was lost")
    violation_rate = accepted_violations / accepted_total if accepted_total else 0.0
    ranking_metrics = {
        "labeled_case_count": len(labeled_metrics),
        "precision_at_10": _mean(item["precision_at_10"] for item in labeled_metrics),
        "recall_at_20": _mean(item["recall_at_20"] for item in labeled_metrics),
        "ndcg_at_10": _mean(item["ndcg_at_10"] for item in labeled_metrics),
        "top_k_jaccard": _mean(replay_jaccards),
    }
    feedback_replay = replay_feedback(feedback_records, recommendations_by_run)
    if not feedback_replay["ok"]:
        errors.append("feedback replay disagreed with regression recommendations")
    return {
        "ok": not errors and violation_rate == 0.0,
        "errors": errors,
        "queries": query_results,
        "listing_count": len(listings),
        "hard_constraint_violation_rate": violation_rate,
        "hard_constraint_checked_count": accepted_total,
        "ranking_metrics": ranking_metrics,
        "quality_report": quality_report,
        "feedback_replay": feedback_replay,
    }


if __name__ == "__main__":
    result = run_regression()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)
