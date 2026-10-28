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
    "game_accounts.policy.v1": {
        "display_name": "游戏账号公开信息入口",
        "entry_url": "https://www.goofish.com/",
        "instruction": "仅允许人工打开官方入口查看公开信息；系统不会抓取、登录、联系、购买、转移或代打。",
    },
    "game_accounts.5173.link.v1": {
        "display_name": "5173 游戏账号",
        "entry_url": "https://www.5173.com/",
        "instruction": "打开官方入口后人工查看公开挂牌；系统不登录、不读取会话、不代购、不转移账号。",
    },
    "game_accounts.taoshouyou.link.v1": {
        "display_name": "淘手游",
        "entry_url": "https://www.taoshouyou.com/",
        "instruction": "打开官方入口后人工查看公开挂牌；系统不登录、不读取会话、不代购、不转移账号。",
    },
    "game_accounts.jaoyimc.link.v1": {
        "display_name": "交易猫",
        "entry_url": "https://jaoyimc.com.cn/",
        "instruction": "打开官方入口后人工查看公开挂牌；系统不登录、不读取会话、不代购、不转移账号。",
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
