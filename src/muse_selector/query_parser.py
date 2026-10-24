"""Deterministic parser for the Hong Kong computers/hardware MVP.

The parser only extracts fields that are explicit in the user's text. It never
uses a model to invent a budget, region, compatibility fact, or stock state.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .contracts import SearchSpec


class PolicyBlockedError(ValueError):
    """Raised when a query requests a first-version blocked action/category."""


_MONEY_NUMBER = r"[\d,]+(?:\.\d+)?"
# Range forms must be checked before the existing upper-bound form.  The
# currency marker may occur before or after the range, and Chinese users often
# use 至/到 rather than a hyphen.
_MONEY_RANGE_RE = re.compile(
    rf"(?:"
    rf"(?:HKD|HK\$|港币|港元)\s*[:：]?\s*(?P<low1>{_MONEY_NUMBER})\s*(?:-|–|—|~|～|至|到)\s*(?P<high1>{_MONEY_NUMBER})"
    rf"|(?P<low2>{_MONEY_NUMBER})\s*(?:-|–|—|~|～|至|到)\s*(?P<high2>{_MONEY_NUMBER})\s*(?:HKD|HK\$|港币|港元)"
    rf")",
    re.I,
)
_MONEY_RE = re.compile(rf"(?:HKD|HK\$|港币|港元|预算)\s*[:：]?\s*(?:不超过|以内|上限|最多)?\s*({_MONEY_NUMBER})\s*(万)?", re.I)
_MONEY_SUFFIX_RE = re.compile(rf"(?P<amount>{_MONEY_NUMBER})\s*(?:HKD|港币|港元)\b", re.I)
_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:内存|RAM|显存|VRAM|SSD|存储|硬盘)?", re.I)
_UNBOUNDED_BUDGET_TOKENS = ("价格不限", "预算不限", "不限预算", "不设预算", "不限制预算", "no budget limit", "unlimited budget")


def _size_gb(value: str, unit: str) -> int:
    number = Decimal(value)
    return int(number * (1024 if unit.upper() == "TB" else 1))


def _money_amount(value: str, wan: str | None = None) -> Decimal:
    amount = Decimal(value.replace(",", ""))
    return amount * (Decimal("10000") if wan else Decimal("1"))


def parse_query(text: str) -> SearchSpec:
    """Parse explicit Hong Kong hardware requirements into ``SearchSpec``."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("query must be non-empty")
    lowered = text.lower()
    if any(token in lowered for token in ("游戏账号", "账号转移", "账号购买", "代打")):
        raise PolicyBlockedError("游戏账号登录、购买、转移和代打不在第一版范围内")
    if any(token in lowered for token in ("169.254.169.254", "127.0.0.1", "localhost", "metadata/latest")):
        raise PolicyBlockedError("blocked network target in query")

    required: dict[str, Any] = {}
    ram = re.search(r"(\d+(?:\.\d+)?)\s*GB\s*(?:内存|RAM)", text, re.I)
    if ram:
        required["ram_gb"] = int(Decimal(ram.group(1)))
    vram = re.search(r"(\d+(?:\.\d+)?)\s*GB\s*(?:以上)?\s*(?:显存|VRAM)", text, re.I)
    if vram:
        required["vram_gb"] = int(Decimal(vram.group(1)))
    storage = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:SSD|存储|硬盘)", text, re.I)
    if storage:
        required["storage_gb"] = _size_gb(storage.group(1), storage.group(2))
    if re.search(r"USB\s*4", text, re.I):
        required["usb4"] = True
    display = re.search(r"(?:双|二|2\s*[x×*]?)\s*4K", text, re.I)
    if display:
        required["display_4k_count"] = 2
    pd = re.search(r"(\d+(?:\.\d+)?)\s*W\s*(?:PD|供电)", text, re.I)
    if pd:
        required["pd_watt"] = int(Decimal(pd.group(1)))

    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    money_range = _MONEY_RANGE_RE.search(text)
    if money_range:
        low = money_range.group("low1") or money_range.group("low2")
        high = money_range.group("high1") or money_range.group("high2")
        budget_min = _money_amount(low)
        budget_max = _money_amount(high)
    else:
        money = _MONEY_RE.search(text)
        if money:
            budget_max = _money_amount(money.group(1), money.group(2))
        else:
            money_suffix = _MONEY_SUFFIX_RE.search(text)
            if money_suffix:
                budget_max = _money_amount(money_suffix.group("amount"))

    category = "computers_hardware"
    if any(token in lowered for token in ("显卡", "gpu", "显存")):
        category = "computers_hardware"
    return SearchSpec(
        query=text.strip(),
        category=category,
        region="HK",
        currency="HKD",
        budget_min=budget_min,
        budget_max=budget_max,
        required_specs=required,
        condition="unknown" if any(token in lowered for token in ("二手", "不限成色")) else "new",
        sources=("ebay.browse.hk.v1",),
    )


def missing_fields(spec: SearchSpec) -> list[str]:
    """Return fields that should be clarified before a high-confidence search."""

    missing: list[str] = []
    if spec.budget_max is None:
        missing.append("budget_max")
    if not spec.required_specs:
        missing.append("required_specs")
    return missing


def has_explicit_unbounded_budget(text: str) -> bool:
    """Return true only when the user explicitly waives a budget cap."""

    lowered = text.lower()
    return any(token in lowered for token in _UNBOUNDED_BUDGET_TOKENS)

