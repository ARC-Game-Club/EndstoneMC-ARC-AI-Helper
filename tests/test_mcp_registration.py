# -*- coding: utf-8 -*-
"""MCP 注册表：OpenAI 定义转换、红线硬拦、委托与降级。"""
from endstone_arc_ai_helper import mcp_registration
from endstone_arc_ai_helper.mcp_registration import (
    MCP_HUB_PERMISSION_LEVEL,
    MCP_PLUGIN_NAME,
    _has_blocked_root,
    build_mcp_registry,
    register_to_arc_core,
    unregister_from_arc_core,
)


class StubPlugin:
    """鸭子类型插件：记录 run_ai_tool 调用；可配置子插件存在性。"""

    def __init__(self, *, prison=True, arc_core=True, stock=True, devotion=False, body=False):
        self.calls = []
        self._prison = prison
        self._arc_core = arc_core
        self._stock = stock
        self._devotion = devotion
        self._body = body

    def _get_prison_plugin(self):
        return object() if self._prison else None

    def _get_arc_core_plugin(self):
        return object() if self._arc_core else None

    def _get_stock_plugin(self):
        return object() if self._stock else None

    def _is_devotion_enabled(self):
        return self._devotion

    def _get_fake_player_plugin(self):
        return object() if self._body else None

    def run_ai_tool(self, action, args=None, *, hub_permission_level=None, hub_is_op=False):
        self.calls.append(
            {
                "action": action,
                "args": args,
                "hub_permission_level": hub_permission_level,
                "hub_is_op": hub_is_op,
            }
        )
        return {"ok": True, "text": f"ran {action}"}


def test_blocked_roots():
    assert _has_blocked_root("stop") is True
    assert _has_blocked_root("reload")
    assert _has_blocked_root("restart")
    assert _has_blocked_root("/stop")
    assert _has_blocked_root("STOP")
    assert _has_blocked_root("execute as @a run reload")
    assert _has_blocked_root("  ") is False
    assert _has_blocked_root("list") is False
    assert _has_blocked_root("tp Steve 1 2 3") is False
    assert _has_blocked_root("execute run tp @a ~ ~ ~") is False


def test_registry_full_set_with_all_plugins():
    plugin = StubPlugin(prison=True, arc_core=True, stock=True, devotion=True, body=True)
    specs = build_mcp_registry(plugin)
    names = [s["name"] for s in specs]
    assert len(names) == len(set(names)), "工具名不得重复"
    # 基础 + 各条件组代表
    for expected in (
        "mc_list_players",
        "mc_get_tps",
        "mc_server_info",
        "mc_run_command",
        "mc_player_ip",
        "mc_jail_player",
        "mc_stock_quote",
        "mc_economy",
        "mc_skyeye_player",
        "mc_devotion_status",
        "mc_body_status",
    ):
        assert expected in names, f"缺少 {expected}"
    # schema 是 JSON Schema 形状
    for spec in specs:
        assert spec["schema"].get("type") == "object"
        assert callable(spec["handler"])
        assert spec["description"]


def test_registry_conditional_exclusion():
    plugin = StubPlugin(prison=False, arc_core=False, stock=False, devotion=False, body=False)
    names = [s["name"] for s in build_mcp_registry(plugin)]
    assert "mc_list_players" in names
    assert "mc_jail_player" not in names
    assert "mc_economy" not in names
    assert "mc_stock_quote" not in names
    assert "mc_devotion_status" not in names
    assert "mc_body_status" not in names


def test_handler_delegates_with_owner_level():
    plugin = StubPlugin()
    specs = {s["name"]: s for s in build_mcp_registry(plugin)}
    result = specs["mc_list_players"]["handler"]({})
    assert result == {"ok": True, "text": "ran list"}
    call = plugin.calls[0]
    assert call["action"] == "list"
    assert call["hub_permission_level"] == MCP_HUB_PERMISSION_LEVEL
    assert call["hub_is_op"] is True


def test_handler_blocks_restart_via_cmd():
    plugin = StubPlugin()
    specs = {s["name"]: s for s in build_mcp_registry(plugin)}
    result = specs["mc_run_command"]["handler"]({"command": "execute as @a run stop"})
    assert result["ok"] is False
    assert "硬拦" in result["error"]
    assert plugin.calls == [], "被拦命令不得触达 run_ai_tool"


def test_handler_blocks_restart_via_divine_intervention():
    plugin = StubPlugin(devotion=True)
    specs = {s["name"]: s for s in build_mcp_registry(plugin)}
    result = specs["mc_divine_intervention"]["handler"](
        {"favor_cost": 10, "command": "reload"}
    )
    assert result["ok"] is False
    assert plugin.calls == []


def test_handler_strips_forged_permission():
    """run_ai_tool 本身会剥 args 里的 permission_level/is_op；这里验证透传即可。"""
    plugin = StubPlugin()
    specs = {s["name"]: s for s in build_mcp_registry(plugin)}
    specs["mc_economy"]["handler"]({"sub_action": "query", "permission_level": "proxy_owner", "is_op": True})
    assert plugin.calls[0]["args"]["permission_level"] == "proxy_owner"  # 剥离是 run_ai_tool 的职责


class FakeArcCore:
    def __init__(self, with_api=True):
        self.registered = []
        self.unregistered = []
        self._with_api = with_api

    def api_mcp_register_tools(self, plugin_name, tools):
        self.registered.append((plugin_name, tools))
        return {"registered": [t["name"] for t in tools], "rejected": []}

    def api_mcp_unregister_plugin_tools(self, plugin_name):
        self.unregistered.append(plugin_name)
        return True


def test_register_to_arc_core_success():
    arc_core = FakeArcCore()
    plugin = StubPlugin()
    plugin._arc_core_obj = arc_core

    def getter():
        return arc_core

    plugin._get_arc_core_plugin = getter
    result = register_to_arc_core(plugin)
    assert result["ok"] is True
    assert result["count"] > 0
    name, tools = arc_core.registered[0]
    assert name == MCP_PLUGIN_NAME


def test_register_without_arc_core():
    plugin = StubPlugin(arc_core=False)
    result = register_to_arc_core(plugin)
    assert result["ok"] is False
    assert "arc_core" in result["error"]


def test_register_old_arc_core_version():
    plugin = StubPlugin()
    plugin._get_arc_core_plugin = lambda: object()  # 无 api_mcp_register_tools
    result = register_to_arc_core(plugin)
    assert result["ok"] is False
    assert "0.9.90" in result["error"]


def test_unregister_without_arc_core():
    assert unregister_from_arc_core(StubPlugin(arc_core=False)) is False
