# -*- coding: utf-8 -*-
"""工具名 → action 的映射表必须覆盖**每一个**已注册的 mc_* 工具。

2026-11-09 实测事故：``mc_arc_tp`` 注册进了工具表，但 ``TOOL_NAME_TO_ACTION``
里漏了它 → ``resolve_tool_action("mc_arc_tp")`` 原样返回 ``"mc_arc_tp"``
→ ``run_ai_tool`` 的分发分支一个都不匹配 → 调用方只看到
``{"ok": false, "error": "未知工具动作: mc_arc_tp"}``。

这条用例把"注册了但没映射"的情况**一次性堵死**：以后再往工具表里加
mc_* 工具却忘了加映射，这里立刻红。
"""
import re
from pathlib import Path

from endstone_arc_ai_helper.local_agent_tools import (
    TOOL_NAME_TO_ACTION,
    resolve_tool_action,
)

TOOLS_PY = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "endstone_arc_ai_helper"
    / "local_agent_tools.py"
)


def _registered_tool_names() -> set:
    """从工具表源码里抠出所有已注册的 ``mc_*`` 工具名。"""
    text = TOOLS_PY.read_text(encoding="utf-8")
    return set(re.findall(r'_fn\(\s*\n?\s*"(mc_[a-z_]+)"', text))


def test_every_registered_tool_has_an_action_mapping():
    registered = _registered_tool_names()
    assert registered, "没抠到任何 mc_* 工具 —— 解析规则该更新了"
    missing = sorted(registered - set(TOOL_NAME_TO_ACTION))
    assert not missing, (
        "这些工具注册了但没有 action 映射，调用时会报'未知工具动作'："
        + ", ".join(missing)
    )


def test_mapping_points_at_a_known_action():
    """映射到的 action 必须是分发分支认识的那些（不能指向不存在的分支）。"""
    known = {
        "list", "tps", "info", "cmd", "economy", "money", "bank",
        "player_basic_info", "resolve_player", "lookup_player",
        "land", "lands", "landmarks", "landmark", "warps",
        "arc_tp", "arc_teleport", "core_tp",
        "jail", "release", "prisoners", "list_prisoners",
        "skyeye_player", "sky_eye_player", "skyeye_combat", "skyeye_events",
        "skyeye_location", "stock_leaderboard", "stock_quote",
        "player_ip", "devotion_status", "devotion_adjust",
        "player_inventory", "accept_offering", "grant_blessing",
        "divine_intervention", "body_status", "body_walk", "body_action",
    }
    unknown = sorted(
        action for action in TOOL_NAME_TO_ACTION.values() if action not in known
    )
    assert not unknown, "映射指向了分发分支不认识的 action：" + ", ".join(unknown)


def test_resolve_tool_action_strips_the_mc_prefix():
    """mc_arc_tp 必须解析成 arc_tp（而不是原样返回）。"""
    assert resolve_tool_action("mc_arc_tp") == "arc_tp"
    assert resolve_tool_action("mc_list_players") == "list"
    # 没登记的名字原样返回（交给上层报错，不是这里崩）
    assert resolve_tool_action("mc_not_a_tool") == "mc_not_a_tool"
