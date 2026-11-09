# -*- coding: utf-8 -*-
"""把本插件的 mc_* 工具注册进 arc_core 的 MCP 服务器（工具定义单一来源）。

- 定义源：local_agent_tools.build_local_agent_tools / build_devotion_agent_tools
  （OpenAI function-calling 格式），此处只做格式转换 + handler 绑定；
  本地 Agent 循环与 MCP 远控共用同一份定义，避免双份维护。
- 权限：MCP 通道 = 127.0.0.1 + token，按服主级（proxy_owner）委托
  plugin.run_ai_tool —— 它内部自带主线程跳转、权限字段剥离与天眼审计。
- 红线：与 arc_core MCP 层同款硬拦 stop/reload/restart（含 execute ... run
  绕过写法）。proxy_owner 档在 AI-Helper 内部本可放行这些命令，MCP 通道
  必须在进入 run_ai_tool 之前拦下——重启权只归服主本人。
"""
from typing import Any, Callable, Dict, List

from .ai_permission import AIPermissionLevel, parse_permission_level
from .local_agent_tools import (
    TOOL_NAME_TO_ACTION,
    build_local_agent_tools,
)

# MCP 注册时使用的插件名（注销时按此键清理）
MCP_PLUGIN_NAME = "arc_ai_helper"

# MCP 通道默认按服主级委托（localhost + token 才能连上，如 ZCode 直连）。
# AstrBot 网关会在 on_using_llm_tool 钩子里把对话发起人档位写进
# args["_mcp_caller_level"]（LLM 之后强制覆盖，无法伪造），有则优先。
MCP_HUB_PERMISSION_LEVEL = "proxy_owner"

MCP_CALLER_LEVEL_KEY = "_mcp_caller_level"

# 与 arc_core mcp_server.BLOCKED_COMMAND_TOKENS 保持一致
_MCP_BLOCKED_ROOTS = {"stop", "reload", "restart"}


def _has_blocked_root(command: str) -> bool:
    """命令首 token 或 execute ... run 之后的 token 命中硬拦名单即拒绝。"""
    parts = str(command or "").strip().lstrip("/").lower().split()
    if not parts:
        return False
    if parts[0] in _MCP_BLOCKED_ROOTS:
        return True
    for index, token in enumerate(parts):
        if token == "run" and index + 1 < len(parts):
            if parts[index + 1] in _MCP_BLOCKED_ROOTS:
                return True
    return False


def _make_handler(plugin: Any, action: str) -> Callable[[Dict[str, Any]], Any]:
    """生成委托 run_ai_tool 的 MCP handler。

    档位路由：args 带 ``_mcp_caller_level``（AstrBot 钩子注入的发起人档位）时按
    该档校验；缺失（ZCode 等服主直连）默认 proxy_owner。任何带 command 参数的
    工具（mc_run_command / mc_divine_intervention 等）都过硬拦名单，防止借
    proxy_owner 档绕过 MCP 层红线。
    """

    def handler(args: Dict[str, Any]) -> Any:
        args = dict(args or {})
        caller_raw = args.pop(MCP_CALLER_LEVEL_KEY, None)
        command = str(args.get("command") or "")
        if command and _has_blocked_root(command):
            return {
                "ok": False,
                "error": (
                    f"命令 '{command.split()[0].lstrip('/')}' 已被 MCP 通道硬拦："
                    "重启/重载必须由服主亲自操作，AI 不代劳。"
                ),
            }
        level = parse_permission_level(
            caller_raw, default=AIPermissionLevel.PROXY_OWNER
        )
        return plugin.run_ai_tool(
            action,
            args,
            hub_permission_level=int(level),
            hub_is_op=bool(level >= AIPermissionLevel.ADMIN),
        )

    return handler


def _openai_tool_to_spec(tool: Dict[str, Any], plugin: Any, server_label: str = "") -> Dict[str, Any]:
    """OpenAI function 格式 → arc_core MCP 注册表条目。

    描述头部追加 [服务器: xxx]——多服聚合接入一个 LLM 时帮模型按用户说的
    服名选对前缀工具（与 ArcCore 内建工具的「作用于服务器」标注同款语义）。
    """
    fn = tool.get("function") or {}
    name = str(fn.get("name") or "").strip()
    action = TOOL_NAME_TO_ACTION.get(name, name)
    parameters = fn.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    description = str(fn.get("description") or name)
    if server_label:
        description = f"[服务器: {server_label}] {description}"
    return {
        "name": name,
        "description": description,
        "schema": parameters,
        "handler": _make_handler(plugin, action),
    }


def build_mcp_registry(plugin: Any) -> List[Dict[str, Any]]:
    """生成当前插件能力下的全部 MCP 工具条目（与本地 Agent 模式同源同条件）。"""
    getter = getattr(plugin, "get_game_server_name", None)
    try:
        server_label = str(getter()).strip() if callable(getter) else ""
    except Exception:
        server_label = ""
    openai_tools = build_local_agent_tools(
        has_prison=getattr(plugin, "_get_prison_plugin", lambda: None)() is not None,
        has_arc_core=getattr(plugin, "_get_arc_core_plugin", lambda: None)() is not None,
        has_stock=getattr(plugin, "_get_stock_plugin", lambda: None)() is not None,
        has_devotion=bool(getattr(plugin, "_is_devotion_enabled", lambda: False)()),
        has_body=getattr(plugin, "_get_fake_player_plugin", lambda: None)() is not None,
    )
    specs = [_openai_tool_to_spec(tool, plugin, server_label) for tool in openai_tools]
    # devotion 工具已由 build_local_agent_tools(has_devotion=True) 分支包含，
    # 与本地 Agent 模式同条件，无需单独注入；按名字去重（保序，先到先得）。
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for spec in specs:
        if spec["name"] and spec["name"] not in seen:
            seen.add(spec["name"])
            unique.append(spec)
    return unique


def register_to_arc_core(plugin: Any) -> Dict[str, Any]:
    """把注册表推给 arc_core。arc_core 未加载/版本过旧时返回注册失败结果。"""
    arc_core = getattr(plugin, "_get_arc_core_plugin", lambda: None)()
    if arc_core is None:
        return {"ok": False, "error": "arc_core not loaded"}
    register = getattr(arc_core, "api_mcp_register_tools", None)
    if not callable(register):
        return {"ok": False, "error": "arc_core < 0.9.90 (no api_mcp_register_tools)"}
    specs = build_mcp_registry(plugin)
    result = register(MCP_PLUGIN_NAME, specs)
    return {"ok": True, "count": len(result.get("registered", [])), "detail": result}


def unregister_from_arc_core(plugin: Any) -> bool:
    arc_core = getattr(plugin, "_get_arc_core_plugin", lambda: None)()
    if arc_core is None:
        return False
    unregister = getattr(arc_core, "api_mcp_unregister_plugin_tools", None)
    if not callable(unregister):
        return False
    try:
        return bool(unregister(MCP_PLUGIN_NAME))
    except Exception:
        return False
