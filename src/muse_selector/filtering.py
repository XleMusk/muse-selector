"""Deterministic hard-constraint filtering for read-only listings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .contracts import FilterRule, Listing, SearchSpec


@dataclass(frozen=True)
class FilterDecision:
    listing_id: str
    accepted: bool
    reasons: tuple[str, ...] = ()


def filter_rules_for_spec(spec: SearchSpec) -> tuple[FilterRule, ...]:
    """Translate explicit required specs into typed, explainable rules."""

    rules: list[FilterRule] = []
    for field, expected in spec.required_specs.items():
        if isinstance(expected, (list, tuple, set)):
            operator = "in"
        elif isinstance(expected, (int, float, Decimal)) and not isinstance(expected, bool):
            operator = "gte"
        else:
            operator = "eq"
        rules.append(FilterRule(field=str(field), operator=operator, expected=expected, rule_id=f"required_spec:{field}"))
    return tuple(rules)


def _matches(required: Any, actual: Any) -> bool:
    if actual is None:
        return False
    if isinstance(required, (list, tuple, set)):
        return actual in required
    if isinstance(required, bool):
        return bool(actual) is required
    if isinstance(required, (int, float, Decimal)):
        try:
            return Decimal(str(actual)) >= Decimal(str(required))
        except (InvalidOperation, TypeError, ValueError):
            return False
    return str(required).strip().lower() == str(actual).strip().lower()


def filter_listings(spec: SearchSpec, listings: Iterable[Listing]) -> tuple[list[Listing], list[FilterDecision]]:
    accepted: list[Listing] = []
    decisions: list[FilterDecision] = []
    for listing in listings:
        reasons: list[str] = []
        total = listing.landed_cost
        if spec.budget_min is not None and (total is None or total < spec.budget_min):
            reasons.append("below_budget_min")
        if spec.budget_max is not None and (total is None or total > spec.budget_max):
            reasons.append("above_budget_max")
        if spec.stock_required and listing.stock_status not in {"in_stock", "preorder"}:
            reasons.append("not_in_stock")
        if listing.specs.get("listing_ended") is True:
            reasons.append("listing_ended")
        if listing.region != spec.region:
            reasons.append("region_mismatch")
        if listing.currency != spec.currency:
            reasons.append("currency_mismatch")
        if spec.condition != "unknown" and listing.condition not in {spec.condition, "unknown"}:
            reasons.append("condition_mismatch")
        if spec.max_delivery_days is not None:
            delivery_days = listing.specs.get("delivery_max_days")
            if delivery_days is None:
                reasons.append("delivery_unknown")
            else:
                try:
                    if Decimal(str(delivery_days)) > Decimal(str(spec.max_delivery_days)):
                        reasons.append("delivery_too_slow")
                except (InvalidOperation, TypeError, ValueError):
                    reasons.append("delivery_unknown")
        for rule in filter_rules_for_spec(spec):
            actual = listing.specs.get(rule.field)
            if actual is None or not _matches(rule.expected, actual):
                reasons.append(rule.rule_id or f"required_spec:{rule.field}")
        if listing.risk_flags:
            reasons.append("risk_flagged")
        decision = FilterDecision(listing.listing_id, not reasons, tuple(reasons))
        decisions.append(decision)
        if decision.accepted:
            accepted.append(listing)
    return accepted, decisions
