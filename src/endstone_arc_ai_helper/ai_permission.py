"""Three-tier AI command permission levels for ARC AI Helper."""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Mapping

_HARMFUL_EFFECTS = frozenset(
    {
        "instant_damage",
        "poison",
        "wither",
        "fatal_poison",
        "darkness",
        "blindness",
        "mining_fatigue",
        "weakness",
        "slowness",
        "nausea",
        "levitation",
    }
)


class AIPermissionLevel(IntEnum):
    """AI Helper permission tiers (low → high)."""

    ASSISTANT = 1
    ADMIN = 2
    PROXY_OWNER = 3


LEVEL_ALIASES: dict[str, AIPermissionLevel] = {
    "assistant": AIPermissionLevel.ASSISTANT,
    "admin": AIPermissionLevel.ADMIN,
    "proxy_owner": AIPermissionLevel.PROXY_OWNER,
    "proxyowner": AIPermissionLevel.PROXY_OWNER,
    "owner": AIPermissionLevel.PROXY_OWNER,
    "助手": AIPermissionLevel.ASSISTANT,
    "管理员": AIPermissionLevel.ADMIN,
    "代理服主": AIPermissionLevel.PROXY_OWNER,
    "服主": AIPermissionLevel.PROXY_OWNER,
}


LEVEL_DISPLAY: dict[AIPermissionLevel, str] = {
    AIPermissionLevel.ASSISTANT: "助手",
    AIPermissionLevel.ADMIN: "管理员",
    AIPermissionLevel.PROXY_OWNER: "代理服主",
}


# Only proxy owner may run these root commands.
PROXY_OWNER_ONLY_ROOTS = frozenset(
    {
        "stop",
        "kill",
        "op",
        "deop",
        "ban",
        "ban-ip",
        "banlist",
        "pardon",
        "pardon-ip",
        "kick",
        "permission",
        "permissions",
        "whitelist",
        "setmaxplayers",
        "reload",
        "restart",
        "save-all",
        "save-on",
        "save-off",
    }
)


def _proxy_owner_only_root_in_command(normalized: str) -> str:
    """Return a proxy-owner-only root if present as the command or after ``run``.

    Blocks admin-level ``execute ... run op`` / ``deop`` etc.
    """
    parts = str(normalized or "").strip().lstrip("/").lower().split()
    if not parts:
        return ""
    if parts[0] in PROXY_OWNER_ONLY_ROOTS:
        return parts[0]
    for index, token in enumerate(parts):
        if token == "run" and index + 1 < len(parts):
            nxt = parts[index + 1]
            if nxt in PROXY_OWNER_ONLY_ROOTS:
                return nxt
    return ""


# Assistant may only use these roots (plus limited execute). No give.
ASSISTANT_ALLOWED_ROOTS = frozenset(
    {
        "tp",
        "teleport",
        "effect",
        "spawnpoint",
        "tell",
        "msg",
        "w",
        "whisper",
        "particle",
        "playsound",
        "execute",
    }
)

# 指令池（chat_config.json 的 command_pools 键）：每档位允许的命令根清单，
# 条目 "*" = 全部（PROXY_OWNER_ONLY_ROOTS 仍硬拦，不受池影响）。
# 默认值 = 历史硬编码行为：助手=白名单、管理员=全部（除敏感根）、代理服主=全部。
DEFAULT_COMMAND_POOLS: dict[str, list[str]] = {
    "assistant": sorted(ASSISTANT_ALLOWED_ROOTS),
    "admin": ["*"],
    "proxy_owner": ["*"],
}


def normalize_command_pools(raw: Any) -> dict[str, list[str]]:
    """规范化指令池配置；缺省/非法档位回退默认。条目为命令根（小写、去斜杠）。"""
    source = raw if isinstance(raw, Mapping) else {}
    pools: dict[str, list[str]] = {}
    for level in ("assistant", "admin", "proxy_owner"):
        entries = source.get(level)
        cleaned: list[str] = []
        if isinstance(entries, (list, tuple, set, frozenset)):
            for item in entries:
                text = str(item or "").strip().lower().lstrip("/")
                if text:
                    cleaned.append(text)
        pools[level] = cleaned if cleaned else list(DEFAULT_COMMAND_POOLS[level])
    return pools


DEFAULT_PARSED_COMMAND_POOLS: dict[str, list[str]] = normalize_command_pools(None)


def _root_in_pool(root: str, pool: list[str]) -> bool:
    if "*" in pool:
        return True
    return root in pool


def _run_tail_root(normalized: str) -> str:
    """``execute ... run <root>`` 的 root（小写）；找不到 run 或无后续 token 返回空串。"""
    parts = normalized.split()
    for index, token in enumerate(parts):
        if token.lower() == "run" and index + 1 < len(parts):
            return parts[index + 1].lower().lstrip("/")
    return ""


def parse_permission_level(raw: Any, default: AIPermissionLevel = AIPermissionLevel.ASSISTANT) -> AIPermissionLevel:
    """Parse a config / payload permission level string."""
    text = str(raw or "").strip().lower()
    if not text:
        return default
    if text.isdigit():
        try:
            value = int(text)
            if value in (1, 2, 3):
                return AIPermissionLevel(value)
        except ValueError:
            pass
    return LEVEL_ALIASES.get(text, default)


def level_display(level: AIPermissionLevel) -> str:
    return LEVEL_DISPLAY.get(level, "助手")


def resolve_ai_capability_ceiling(
    chat_config: Mapping[str, Any] | None = None,
) -> AIPermissionLevel:
    """AI capability ceiling from config (what 天星 itself is allowed to do).

    ``ai_capability_level`` / legacy ``default_permission_level`` describe the
    agent plugin's power cap, NOT each requester's identity.
    """
    cfg = chat_config or {}
    raw = cfg.get("ai_capability_level")
    if raw in (None, ""):
        raw = cfg.get("default_permission_level")
    # Historical configs used "admin" to mean "天星 has admin tools".
    return parse_permission_level(raw, AIPermissionLevel.ADMIN)


def resolve_player_permission_level(
    chat_config: Mapping[str, Any] | None = None,
) -> AIPermissionLevel:
    """Identity tier for normal (non-OP) players.

    Config keys (first match wins):
    ``player_permission_level``, ``normal_player_permission_level``.
    Default: assistant.
    """
    cfg = chat_config or {}
    raw = cfg.get("player_permission_level")
    if raw in (None, ""):
        raw = cfg.get("normal_player_permission_level")
    return parse_permission_level(raw, AIPermissionLevel.ASSISTANT)


def resolve_op_permission_level(
    chat_config: Mapping[str, Any] | None = None,
) -> AIPermissionLevel | None:
    """Identity tier for OP players, or None when OP should not be elevated.

    ``op_permission_level`` is preferred. Legacy ``op_maps_to_admin``:
    true → admin, false → no OP elevation (keep player tier).
    Default when neither set: admin.
    """
    cfg = chat_config or {}
    raw = cfg.get("op_permission_level")
    if raw not in (None, ""):
        return parse_permission_level(raw, AIPermissionLevel.ADMIN)
    if "op_maps_to_admin" in cfg and not bool(cfg.get("op_maps_to_admin")):
        return None
    return AIPermissionLevel.ADMIN


def resolve_requester_level(
    *,
    player: Any = None,
    chat_config: Mapping[str, Any] | None = None,
    payload_level: Any = None,
    payload_is_op: bool = False,
    op_maps_to_admin: bool | None = None,
    trust_payload: bool = True,
) -> AIPermissionLevel:
    """Resolve the caller's identity tier (never raised by capability ceiling)."""
    cfg = dict(chat_config or {})
    # Call-site override for legacy tests / callers that still pass the flag.
    if op_maps_to_admin is not None and "op_permission_level" not in cfg:
        cfg["op_maps_to_admin"] = bool(op_maps_to_admin)

    level = resolve_player_permission_level(cfg)

    overrides = cfg.get("permission_overrides") or {}
    if isinstance(overrides, dict) and player is not None:
        keys: list[str] = []
        xuid = str(getattr(player, "xuid", "") or "").strip()
        name = str(getattr(player, "name", "") or "").strip()
        if xuid:
            keys.append(xuid)
        if name:
            keys.append(name)
            keys.append(name.lower())
        for key in keys:
            if key in overrides:
                level = max(level, parse_permission_level(overrides[key], AIPermissionLevel.ASSISTANT))
                break

    perm_api = getattr(player, "has_permission", None) if player is not None else None
    if callable(perm_api):
        if perm_api("arc_ai_helper.permission.proxy_owner"):
            level = AIPermissionLevel.PROXY_OWNER
        elif perm_api("arc_ai_helper.permission.admin"):
            level = max(level, AIPermissionLevel.ADMIN)
        elif perm_api("arc_ai_helper.permission.assistant"):
            level = max(level, AIPermissionLevel.ASSISTANT)

    op_tier = resolve_op_permission_level(cfg)
    if op_tier is not None and player is not None and bool(getattr(player, "is_op", False)):
        level = max(level, op_tier)

    # Local player object wins; ignore hub echo that could self-amplify.
    if player is not None or not trust_payload:
        return level

    if payload_level not in (None, ""):
        level = max(level, parse_permission_level(payload_level, AIPermissionLevel.ASSISTANT))

    if payload_is_op and op_tier is not None:
        level = max(level, op_tier)

    return level


def resolve_permission_level(
    *,
    player: Any = None,
    chat_config: Mapping[str, Any] | None = None,
    payload_level: Any = None,
    payload_is_op: bool = False,
    op_maps_to_admin: bool | None = None,
) -> AIPermissionLevel:
    """Effective level = min(AI capability ceiling, requester identity)."""
    ceiling = resolve_ai_capability_ceiling(chat_config)
    requester = resolve_requester_level(
        player=player,
        chat_config=chat_config,
        payload_level=payload_level,
        payload_is_op=payload_is_op,
        op_maps_to_admin=op_maps_to_admin,
        trust_payload=True,
    )
    return AIPermissionLevel(min(int(ceiling), int(requester)))


def validate_command_for_level(
    command: str,
    level: AIPermissionLevel,
    *,
    bound_player_name: str = "",
    is_bound_self_help: bool = False,
    allow_assistant_item_grant: bool = False,
    pools: Any = None,
) -> tuple[bool, str]:
    """Return whether a console command is allowed for the given AI permission level.

    ``allow_assistant_item_grant``：仅神灵模式 ``mc_divine_intervention`` 的物品神恩
    可在助手档临时放行 ``give``（须已扣近期好感）；``mc_run_command`` 不可传此标志。

    ``pools``：指令池配置（chat_config.json 的 ``command_pools``），None = 内置默认
    （助手=ASSISTANT_ALLOWED_ROOTS 白名单、管理员/代理服主=全部）。``execute`` 需
    root 在池内且 ``run`` 后的命令根也在池内。PROXY_OWNER_ONLY_ROOTS 恒硬拦。
    """
    pool_map = normalize_command_pools(pools) if pools is not None else DEFAULT_PARSED_COMMAND_POOLS
    normalized = str(command or "").strip().lstrip("/").strip()
    if not normalized:
        return False, "命令为空"

    parts = normalized.split()
    root = parts[0].lower() if parts else ""

    if level >= AIPermissionLevel.PROXY_OWNER:
        return True, ""

    forbidden = _proxy_owner_only_root_in_command(normalized)
    if forbidden:
        return False, f"该指令仅代理服主级别可用: /{forbidden}"

    if is_bound_self_help and level < AIPermissionLevel.ADMIN:
        from .bound_self_help import validate_bound_self_help_command

        return validate_bound_self_help_command(normalized, bound_player_name)

    is_admin = level >= AIPermissionLevel.ADMIN
    pool = pool_map["admin" if is_admin else "assistant"]
    tier_label = "管理员" if is_admin else "助手"

    if root == "give" and not is_admin and allow_assistant_item_grant:
        if len(parts) >= 2 and parts[1].startswith("@"):
            return False, "助手级别 give 不可使用 @ 选择器"
        return True, ""

    if root == "execute":
        # execute 只是包装壳：判定实际执行的 run 后命令根是否在池内。
        tail = _run_tail_root(normalized)
        if not tail or not _root_in_pool(tail, pool):
            return False, f"execute 仅允许 run 后接 {tier_label}指令池内的命令"
        return True, ""

    if not _root_in_pool(root, pool):
        if is_admin:
            return False, f"管理员级别指令池不含 /{root}（可在 chat_config.json 的 command_pools.admin 中添加）"
        return False, f"助手级别不可用 /{root}，需要管理员及以上权限"

    if root == "effect" and not is_admin and len(parts) >= 3 and parts[2].lower() in _HARMFUL_EFFECTS:
        return False, "助手级别不允许使用负面效果"

    return True, ""


def require_admin_level(level: AIPermissionLevel) -> str:
    """Return an error message when admin+ is required, or empty string if allowed."""
    if level >= AIPermissionLevel.ADMIN:
        return ""
    return f"没有权限：该功能需要管理员（{level_display(AIPermissionLevel.ADMIN)}）及以上级别。"
