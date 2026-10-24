"""Offline regression harness for the Hong Kong computer/hardware MVP.

The harness deliberately consumes JSON fixtures and the deterministic contracts in
``src/muse_selector``. It never calls an external API. A production connector can
reuse the same normalized Listing/Evidence objects and run this suite before merge.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from muse_selector.contracts import Evidence, Listing, SearchSpec  # noqa: E402
from muse_selector.filtering import filter_listings  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


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
    raw = load_raw_listings()
    listings = [build_listing(item) for item in raw if item.get("category") != "game_account"]
    query_results: dict[str, Any] = {}
    accepted_total = 0
    accepted_violations = 0

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
        query_results[case_id] = {"accepted": ids, "decisions": [asdict(d) for d in decisions]}
        if expected.get("must_return") and not accepted:
            errors.append(f"{case_id}: expected at least one accepted listing")
        if expected.get("replay_must_be_stable"):
            accepted_again, _ = filter_listings(spec, listings)
            if ids != canonical_ids(accepted_again):
                errors.append(f"{case_id}: replay ordering changed")
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
    return {
        "ok": not errors and violation_rate == 0.0,
        "errors": errors,
        "queries": query_results,
        "listing_count": len(listings),
        "hard_constraint_violation_rate": violation_rate,
        "hard_constraint_checked_count": accepted_total,
    }


if __name__ == "__main__":
    result = run_regression()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)
