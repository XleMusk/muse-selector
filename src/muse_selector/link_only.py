"""Manual, link-only entry plans for sources without listing-search access."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import SearchSpec


_PLATFORM_ENTRIES: Mapping[str, Mapping[str, str]] = {
    "xianyu.partner.v1": {
        "display_name": "闲鱼",
        "entry_url": "https://www.goofish.com/",
        "instruction": "打开官方入口后，在平台内手动搜索下方查询；平台页面负责实际结果展示。",
    },
    "zhuanzhuan.recommerce.mcp.v1": {
        "display_name": "转转",
        "entry_url": "https://www.zhuanzhuan.com/",
        "instruction": "打开官方入口后，在平台内手动搜索下方查询；当前官方 MCP 只提供估价/回收入口。",
    },
}


def build_link_only_plan(spec: SearchSpec) -> list[dict[str, Any]]:
    """Return stable, read-only manual entry cards for requested sources."""

    plans: list[dict[str, Any]] = []
    for source_id in spec.sources:
        details = _PLATFORM_ENTRIES.get(source_id)
        if details is None:
            continue
        plans.append(
            {
                "source_id": source_id,
                "display_name": details["display_name"],
                "status": "link_only",
                "entry_url": details["entry_url"],
                "manual_query": spec.query,
                "instruction": details["instruction"],
                "read_only": True,
                "retrieval": "manual_platform_search",
            }
        )
    return plans
