"""Evidence-first result cards for the read-only MVP."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .contracts import Evidence, Listing, SearchSpec
from .filtering import FilterDecision


@dataclass(frozen=True)
class ResultCard:
    listing_id: str
    title: str
    source_id: str
    url: str
    price: str | None
    landed_cost: str | None
    currency: str
    source_observed_at: str
    stock_status: str
    condition: str
    specs: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    risk_flags: tuple[str, ...]
    status: str = "recommended"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = [dict(item) for item in self.evidence]
        result["risk_flags"] = list(self.risk_flags)
        return result


def _money(value: Decimal | None) -> str | None:
    return f"{value:.2f}" if value is not None else None


def build_card(listing: Listing, evidence: Iterable[Evidence], *, status: str = "recommended") -> ResultCard:
    return ResultCard(
        listing_id=listing.listing_id,
        title=listing.title,
        source_id=listing.source_id,
        url=listing.url,
        price=_money(listing.price),
        landed_cost=_money(listing.landed_cost),
        currency=listing.currency,
        source_observed_at=listing.source_observed_at,
        stock_status=listing.stock_status,
        condition=listing.condition,
        specs=dict(listing.specs),
        evidence=tuple(item.to_dict() for item in evidence),
        risk_flags=listing.risk_flags,
        status=status,
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render a compact, inspectable result card report."""

    spec = payload["search_spec"]
    lines = [
        "# Muse Selector 结果卡",
        "",
        f"查询：{spec['query']}",
        f"地区/币种：{spec['region']} / {spec['currency']}",
        f"预算上限：{spec.get('budget_max') or '未指定'}",
        "",
        "## 推荐结果",
        "",
    ]
    cards = payload.get("recommended", [])
    if not cards:
        lines.append("没有满足全部硬约束的结果。")
    for index, card in enumerate(cards, 1):
        lines.extend([
            f"### {index}. {card['title']}",
            f"- 到手价：{card['landed_cost'] or 'unknown'} {card['currency']}",
            f"- 来源观测时间：{card.get('source_observed_at') or 'unknown'}",
            f"- 状态：{card['stock_status']}；成色：{card['condition']}",
            f"- 规格：{card['specs'] or 'unknown'}",
            f"- 来源：[打开原平台]({card['url']})",
            f"- 风险：{', '.join(card['risk_flags']) if card['risk_flags'] else '未标记'}",
            f"- 证据字段：{', '.join(item['field'] for item in card['evidence']) or 'unknown'}",
            "",
        ])
    if payload.get("rejected"):
        lines.extend(["## 被硬约束过滤的结果", ""])
        for item in payload["rejected"]:
            lines.append(f"- `{item['listing_id']}`：{', '.join(item['reasons'])}")
    if payload.get("dropped"):
        lines.extend(["", "## 未进入推荐的来源记录", ""])
        for item in payload["dropped"]:
            lines.append(f"- `{item['listing_id']}`：{item['reason']}")
    return "\n".join(lines).rstrip() + "\n"

