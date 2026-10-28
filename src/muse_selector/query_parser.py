"""Deterministic parser for market-specific computers/hardware queries.

The parser only extracts fields that are explicit in the user's text. It never
uses a model to invent a budget, region, compatibility fact, or stock state.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .category_registry import resolve_product_category
from .contracts import SearchSpec


class PolicyBlockedError(ValueError):
    """Raised when a query requests a first-version blocked action/category.

    Structured fields let the read-only pipeline report a domain-specific
    policy decision without routing the request through a product connector.
    """

    def __init__(
        self,
        message: str,
        *,
        domain: str = "policy",
        source_id: str = "policy.guard",
        reason_code: str = "blocked_action",
    ) -> None:
        super().__init__(message)
        self.domain = domain
        self.source_id = source_id
        self.reason_code = reason_code


_MONEY_NUMBER = r"[\d,]+(?:\.\d+)?"
_MONEY_UNIT = r"(?:万|千|[kK])"
_MONEY_VALUE = rf"{_MONEY_NUMBER}\s*{_MONEY_UNIT}?"
# Range forms must be checked before the existing upper-bound form.  The
# currency marker may occur before or after the range, and Chinese users often
# use 至/到 rather than a hyphen.
_MONEY_RANGE_RE = re.compile(
    rf"(?:"
    rf"(?:HKD|HK\$|港币|港幣|港元)\s*[:：]?\s*(?P<low1>{_MONEY_VALUE})\s*(?:-|–|—|~|～|至|到)\s*(?P<high1>{_MONEY_VALUE})"
    rf"|(?P<low2>{_MONEY_VALUE})\s*(?:-|–|—|~|～|至|到)\s*(?P<high2>{_MONEY_VALUE})\s*(?:HKD|HK\$|港币|港幣|港元)"
    rf")",
    re.I,
)
_MONEY_RE = re.compile(
    rf"(?:HKD|HK\$|港币|港幣|港元|预算|預算)\s*[:：]?\s*(?:不超过|以内|上限|最多)?\s*"
    rf"(?P<amount>{_MONEY_NUMBER})\s*(?P<unit>{_MONEY_UNIT})?",
    re.I,
)
_MONEY_SUFFIX_RE = re.compile(
    rf"(?P<amount>{_MONEY_NUMBER})\s*(?P<unit>{_MONEY_UNIT})?\s*(?:HKD|港币|港幣|港元)\b", re.I
)
_CNY_MONEY_RANGE_RE = re.compile(
    rf"(?:"
    rf"(?:CNY|人民币|预算|預算)\s*[:：]?\s*(?P<low1>{_MONEY_VALUE})\s*(?:-|–|—|~|～|至|到)\s*(?P<high1>{_MONEY_VALUE})"
    rf"|(?P<low2>{_MONEY_VALUE})\s*(?:-|–|—|~|～|至|到)\s*(?P<high2>{_MONEY_VALUE})\s*(?:CNY|人民币|元|￥|¥)"
    rf")",
    re.I,
)
_CNY_MONEY_RE = re.compile(
    rf"(?:CNY|人民币|预算|預算)\s*[:：]?\s*(?:不超过|以内|上限|最多)?\s*"
    rf"(?P<amount>{_MONEY_NUMBER})\s*(?P<unit>{_MONEY_UNIT})?",
    re.I,
)
_CNY_MONEY_SUFFIX_RE = re.compile(
    rf"(?P<amount>{_MONEY_NUMBER})\s*(?P<unit>{_MONEY_UNIT})?\s*(?:CNY|人民币|元|￥|¥)", re.I
)
_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:内存|RAM|显存|VRAM|SSD|存储|硬盘)?", re.I)
_DELIVERY_DAYS_RE = re.compile(
    r"(?:配送|送达|到货|delivery)\s*(?:在|于|within)?\s*(?P<days>\d+)\s*(?:天|日|days?)\s*(?:内|以内)?|"
    r"(?P<days_prefix>\d+)\s*(?:天|日)\s*(?:内|以内)\s*(?:送达|到货|配送)",
    re.I,
)
_UNBOUNDED_BUDGET_TOKENS = ("价格不限", "预算不限", "預算不限", "不限预算", "不限預算", "不设预算", "不設預算", "不限制预算", "不限制預算", "no budget limit", "unlimited budget")
_GAME_ACCOUNT_DOMAIN_TOKENS = (
    "游戏账号",
    "游戏账户",
    "游戏帐号",
    "游戏帐户",
    "遊戲帳號",
    "遊戲帳戶",
    "game account",
)
_ACCOUNT_POLICY_TOKENS = (
    "账号转移",
    "账号转让",
    "账号交易",
    "账号购买",
    "账号出售",
    "出售账号",
    "购买账号",
    "帐号转移",
    "帐号转让",
    "帐号交易",
    "帐号购买",
    "帐号出售",
    "出售帐号",
    "购买帐号",
    "帳號轉移",
    "帳號轉讓",
    "帳號交易",
    "帳號購買",
    "帳號出售",
    "出售帳號",
    "購買帳號",
    "帳戶轉移",
    "帳戶轉讓",
    "帳戶交易",
    "帳戶購買",
    "帳戶出售",
    "出售帳戶",
    "購買帳戶",
    "代打",
    "代练",
    "代練",
    "account transfer",
    "account sale",
    "account purchase",
    "account trading",
    "account boosting",
    "boosting service",
)
_ACCOUNT_ACTION_TOKENS = (
    "登录", "登入", "密码", "cookie", "验证码", "支付", "购买", "購買", "出售", "轉售",
    "转移", "轉移", "转让", "轉讓", "交易", "代打", "代练", "代練", "login", "password",
    "payment", "purchase", "sale", "transfer", "trading", "boosting",
)


def _size_gb(value: str, unit: str) -> int:
    number = Decimal(value)
    return int(number * (1024 if unit.upper() == "TB" else 1))


def _money_amount(value: str, unit: str | None = None) -> Decimal:
    if unit is None:
        value_match = re.fullmatch(rf"(?P<number>{_MONEY_NUMBER})\s*(?P<unit>{_MONEY_UNIT})?", value, re.I)
        if value_match:
            value = value_match.group("number")
            unit = value_match.group("unit")
    amount = Decimal(value.replace(",", ""))
    if unit == "万":
        return amount * Decimal("10000")
    if unit == "千" or (unit is not None and unit.lower() == "k"):
        return amount * Decimal("1000")
    return amount


def parse_query(text: str) -> SearchSpec:
    """Parse explicit market and hardware requirements into ``SearchSpec``."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("query must be non-empty")
    lowered = text.lower()
    game_account_query = any(token in lowered for token in _GAME_ACCOUNT_DOMAIN_TOKENS)
    explicit_domestic = any(token in lowered for token in ("中国大陆", "中国内地", "大陆", "国内", "人民币", "cny", "￥", "¥"))
    explicit_hk = any(token in lowered for token in ("香港", "港币", "港幣", "港元", "hkd", "hk$"))
    # Second-hand electronics are the domestic product line by default. An
    # explicit Hong Kong marker still wins for historical HK use cases.
    explicit_second_hand = any(
        token in lowered for token in ("二手", "闲置", "中古", "used", "pre-owned", "preowned")
    )
    domestic = (explicit_domestic or explicit_second_hand or game_account_query or bool(re.search(rf"{_MONEY_VALUE}\s*元", text))) and not explicit_hk
    account_action = any(token in lowered for token in (*_ACCOUNT_POLICY_TOKENS, *_ACCOUNT_ACTION_TOKENS))
    if any(token in lowered for token in _ACCOUNT_POLICY_TOKENS) or (game_account_query and account_action):
        raise PolicyBlockedError(
            "游戏账号登录、购买、转移和代打不在第一版范围内",
            domain="game_accounts",
            source_id="game_accounts.policy.v1",
            reason_code="account_transaction_blocked",
        )
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

    delivery = _DELIVERY_DAYS_RE.search(text)
    max_delivery_days = int(delivery.group("days") or delivery.group("days_prefix")) if delivery else None

    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    money_range = (_CNY_MONEY_RANGE_RE if domestic else _MONEY_RANGE_RE).search(text)
    if money_range:
        low = money_range.group("low1") or money_range.group("low2")
        high = money_range.group("high1") or money_range.group("high2")
        budget_min = _money_amount(low)
        budget_max = _money_amount(high)
    else:
        money = (_CNY_MONEY_RE if domestic else _MONEY_RE).search(text)
        if money:
            budget_max = _money_amount(money.group("amount"), money.group("unit"))
        else:
            money_suffix = (_CNY_MONEY_SUFFIX_RE if domestic else _MONEY_SUFFIX_RE).search(text)
            if money_suffix:
                budget_max = _money_amount(money_suffix.group("amount"), money_suffix.group("unit"))

    category = "game_accounts" if game_account_query else "computers_hardware"
    product_type = "game_account" if game_account_query else resolve_product_category(text)
    clarification_fields: list[str] = []
    if budget_max is None:
        clarification_fields.append("budget_max")
    parse_confidence = 0.9 if product_type != "general_hardware" and clarification_fields else 1.0
    if product_type == "general_hardware":
        parse_confidence = 0.8
    return SearchSpec(
        query=text.strip(),
        category=category,
        region="CN" if domestic else "HK",
        currency="CNY" if domestic else "HKD",
        budget_min=budget_min,
        budget_max=budget_max,
        required_specs=required,
        condition="unknown" if any(token in lowered for token in ("二手", "不限成色")) else "new",
        max_delivery_days=max_delivery_days,
        sources=(
            "game_accounts.5173.link.v1",
            "game_accounts.taoshouyou.link.v1",
            "game_accounts.jaoyimc.link.v1",
        ) if game_account_query else (
            ("xianyu.partner.v1", "zhuanzhuan.recommerce.mcp.v1") if domestic else ("ebay.browse.hk.v1",)
        ),
        product_type=product_type,
        parse_confidence=parse_confidence,
        clarification_fields=tuple(clarification_fields),
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

