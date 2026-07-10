#!/usr/bin/env python3
"""UsageTray Telegram bridge.

Reads sanitized JSON from stdin and writes sanitized JSON to stdout.
Never prints bot tokens, cookies, session keys, or raw credentials.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


APP_DIR_NAME = "UsageTray"
SETTINGS_FILE = "telegram-settings.json"
TOKEN_FILE = "telegram-token.bin"
STATE_FILE = "telegram-alert-state.json"
UPDATES_STATE_FILE = "telegram-updates-state.json"
THRESHOLDS = [50, 85, 95]
DPAPI_FLAGS = 0x1
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo

AGENT_LABELS = {"codex": "Codex", "claude": "Claude"}
AGENT_ORDER = ["claude", "codex"]  # Fixed report order, regardless of which agent triggered the alert.
WINDOW_LABELS = {
    "five_hour": "5 小時",
    "weekly": "每週",
    "weekly_scoped": "每週 Scoped",
}
WINDOW_ORDER = {
    "codex": ["five_hour", "weekly"],
    "claude": ["five_hour", "weekly", "weekly_scoped"],
}
WINDOW_SHORT_LABELS = {
    "five_hour": "5h ",
    "weekly": "週 ",
    "weekly_scoped": "週S",
}
WEEKDAY_LABELS = "一二三四五六日"
MDV2_SPECIAL_CHARS = r"_*[]()~`>#+-=|{}.!"
ERROR_HINTS = {
    "claude_refresh_failed": "Claude 權杖刷新失敗，請重新登入 Claude Code。",
    "claude_refresh_cooldown": "Claude 權杖刷新剛失敗，冷卻中，稍後會自動重試。",
    "claude_auth_expired": "Claude Code 登入已過期，請重新登入。",
    "claude_credentials_not_found": "找不到 Claude Code 登入資訊，請先登入 Claude Code。",
    "codex_command_not_found": "找不到 Codex，請確認已安裝。",
}


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32


def app_dir() -> Path:
    base = os.environ.get("APPDATA")
    if not base:
        raise RuntimeError("APPDATA is unavailable.")
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_dir() / SETTINGS_FILE


def token_path() -> Path:
    return app_dir() / TOKEN_FILE


def state_path() -> Path:
    return app_dir() / STATE_FILE


def updates_state_path() -> Path:
    return app_dir() / UPDATES_STATE_FILE


def read_json_stdin() -> dict[str, Any]:
    raw = sys.stdin.buffer.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def write_json_stdout(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {"enabled": False, "chat_id": None, "chat_label": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "chat_id": None, "chat_label": None}
    return {
        "enabled": bool(data.get("enabled", False)),
        "chat_id": data.get("chat_id"),
        "chat_label": data.get("chat_label"),
    }


def save_settings(data: dict[str, Any]) -> None:
    settings_path().write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {"thresholds": {}, "errors": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"thresholds": {}, "errors": {}}
    if not isinstance(data, dict):
        return {"thresholds": {}, "errors": {}}
    return {
        "thresholds": data.get("thresholds", {}) if isinstance(data.get("thresholds"), dict) else {},
        "errors": data.get("errors", {}) if isinstance(data.get("errors"), dict) else {},
    }


def save_state(data: dict[str, Any]) -> None:
    state_path().write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def load_updates_state() -> dict[str, int]:
    path = updates_state_path()
    if not path.exists():
        return {"last_update_id": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last_update_id": 0}
    last_update_id = data.get("last_update_id") if isinstance(data, dict) else None
    if not isinstance(last_update_id, int):
        return {"last_update_id": 0}
    return {"last_update_id": last_update_id}


def save_updates_state(data: dict[str, int]) -> None:
    updates_state_path().write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, Any]:
    if not data:
        return DATA_BLOB(0, None), None
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect_bytes(data: bytes) -> bytes:
    source, source_buffer = blob_from_bytes(data)
    target = DATA_BLOB()
    result = crypt32.CryptProtectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        DPAPI_FLAGS,
        ctypes.byref(target),
    )
    if not result:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        if target.pbData:
            kernel32.LocalFree(target.pbData)
        del source_buffer


def unprotect_bytes(data: bytes) -> bytes:
    source, source_buffer = blob_from_bytes(data)
    target = DATA_BLOB()
    result = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        DPAPI_FLAGS,
        ctypes.byref(target),
    )
    if not result:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        if target.pbData:
            kernel32.LocalFree(target.pbData)
        del source_buffer


def save_token(token: str) -> None:
    encrypted = protect_bytes(token.encode("utf-8"))
    token_path().write_bytes(encrypted)


def delete_token() -> None:
    try:
        token_path().unlink()
    except FileNotFoundError:
        pass


def load_token() -> str | None:
    path = token_path()
    if not path.exists():
        return None
    encrypted = path.read_bytes()
    if not encrypted:
        return None
    return unprotect_bytes(encrypted).decode("utf-8")


def has_token() -> bool:
    return token_path().exists() and token_path().stat().st_size > 0


def telegram_api(token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {error.code}: {body[:160]}")
    except urllib.error.URLError as error:
        raise RuntimeError(f"Telegram connection failed: {error.reason}")
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram API error: {parsed.get('description', 'unknown error')}")
    return parsed


def parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(LOCAL_TZ)


def format_stamp(value: str | None) -> str:
    parsed = parse_dt(value)
    if not parsed:
        return "-"
    return parsed.strftime("%m/%d %H:%M")


def resolve_reference(snapshot: dict[str, Any]) -> dt.datetime:
    parsed = parse_dt(snapshot.get("captured_at"))
    return parsed or dt.datetime.now(dt.timezone.utc).astimezone(LOCAL_TZ)


def format_reset(value: str | None, reference: dt.datetime | None = None) -> str:
    parsed = parse_dt(value)
    if not parsed:
        return "無重置時間"
    now_ref = reference or dt.datetime.now(dt.timezone.utc).astimezone(LOCAL_TZ)
    day_delta = (parsed.date() - now_ref.date()).days
    time_text = parsed.strftime("%H:%M")
    if day_delta <= 0:
        return f"今天 {time_text}"
    if day_delta == 1:
        return f"明天 {time_text}"
    weekday = WEEKDAY_LABELS[parsed.weekday()]
    return f"{parsed.strftime('%m/%d')} 週{weekday} {time_text}"


def format_reset_compact(value: str | None, reference: dt.datetime) -> str:
    # Shorter than format_reset(): used inside the per-window report table,
    # where the header line already established "today" via format_reset().
    parsed = parse_dt(value)
    if not parsed:
        return "無重置時間"
    day_delta = (parsed.date() - reference.date()).days
    time_text = parsed.strftime("%H:%M")
    if day_delta <= 0:
        return f"重置 {time_text}"
    if day_delta == 1:
        return f"明天{time_text}"
    return f"{parsed.strftime('%m/%d')} {time_text}"


def escape_markdown_v2(text: str) -> str:
    return "".join(f"\\{ch}" if ch in MDV2_SPECIAL_CHARS else ch for ch in text)


def escape_code_block(text: str) -> str:
    # Inside a MarkdownV2 code fence only backslash and backtick need escaping.
    return text.replace("\\", "\\\\").replace("`", "\\`")


def alert_cycle_id(window: dict[str, Any]) -> str:
    parsed = parse_dt(window.get("reset_at"))
    if parsed:
        return f"reset:{parsed.strftime('%Y-%m-%dT%H:%M')}"
    return f"duration:{window.get('window_duration_mins')}"


# Claude's OAuth endpoint jitters reset_at by seconds between polls, which can
# flip the minute-precision cycle id across a minute boundary and fake a "new
# cycle". Real new cycles differ by hours, so anything within this window is
# treated as the same cycle.
CYCLE_TOLERANCE_MINS = 30


def same_cycle(stored: Any, current: str) -> bool:
    if not isinstance(stored, str):
        return False
    if stored == current:
        return True
    if not (stored.startswith("reset:") and current.startswith("reset:")):
        return False
    a = parse_dt(stored[len("reset:"):])
    b = parse_dt(current[len("reset:"):])
    if not a or not b:
        return False
    return abs((a - b).total_seconds()) <= CYCLE_TOLERANCE_MINS * 60


def reached_thresholds(used: float) -> list[int]:
    return [threshold for threshold in THRESHOLDS if used >= threshold]


def threshold_emoji(threshold: int) -> str:
    if threshold >= 95:
        return "🚨"
    if threshold >= 85:
        return "⚠️"
    return "🔔"


def alert_message(snapshot: dict[str, Any], crossings: list[dict[str, Any]]) -> str:
    """One combined message for every threshold crossed in this cycle run.

    Each crossing dict: agent, window_name, used, remaining, reset_at, threshold.
    """
    reference = resolve_reference(snapshot)
    report = "\n".join(build_report_lines(snapshot, reference))
    header_lines: list[str] = []
    for crossing in crossings:
        agent_label = AGENT_LABELS.get(crossing["agent"], crossing["agent"])
        window_label = WINDOW_SHORT_LABELS.get(
            crossing["window_name"], crossing["window_name"].replace("_", " ")
        ).strip()
        threshold = crossing["threshold"]
        header_lines.append(
            f"{threshold_emoji(threshold)} {agent_label} {window_label} 已達 {threshold}%"
            f"（已用 {crossing['used']:.0f}%，重置 {format_reset(crossing['reset_at'], reference)}）"
        )
    footer = f"更新：{format_stamp(snapshot.get('captured_at'))}"
    return "\n\n".join(
        [
            escape_markdown_v2("\n".join(header_lines)),
            f"```\n{escape_code_block(report)}\n```",
            escape_markdown_v2(footer),
        ]
    )


def error_message(snapshot: dict[str, Any], agent: str, code: str, text: str | None) -> str:
    agent_label = AGENT_LABELS.get(agent, agent)
    hint = ERROR_HINTS.get(code) or text or code.replace("_", " ")
    report = "\n".join(build_report_lines(snapshot))
    header = "\n".join([f"❗ {agent_label} 資料來源異常", hint])
    footer = f"更新：{format_stamp(snapshot.get('captured_at'))}"
    return "\n\n".join(
        [
            escape_markdown_v2(header),
            f"```\n{escape_code_block(report)}\n```",
            escape_markdown_v2(footer),
        ]
    )


def usage_command_message(snapshot: dict[str, Any]) -> str:
    report = "\n".join(build_report_lines(snapshot))
    footer = f"更新：{format_stamp(snapshot.get('captured_at'))}"
    return "\n\n".join(
        [
            escape_markdown_v2("📊 目前用量"),
            f"```\n{escape_code_block(report)}\n```",
            escape_markdown_v2(footer),
        ]
    )


def send_message(token: str, chat_id: str, text: str, parse_mode: str | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    telegram_api(token, "sendMessage", payload)


def render_bar(used: float | None, width: int = 10) -> str:
    if not isinstance(used, (int, float)) or used != used:  # noqa: PLR0124 (NaN check)
        return "?" * width
    clamped = max(0.0, min(100.0, float(used)))
    filled = max(0, min(width, round(clamped / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def build_report_lines(snapshot: dict[str, Any], reference: dt.datetime | None = None) -> list[str]:
    reference = reference or resolve_reference(snapshot)
    agents = snapshot.get("agents", {})
    lines: list[str] = []
    for agent_name in AGENT_ORDER:
        agent = agents.get(agent_name) if isinstance(agents, dict) else None
        lines.append(AGENT_LABELS[agent_name])
        if not isinstance(agent, dict) or agent.get("available") is False:
            lines.append("資料無法取得")
            lines.append("")
            continue
        windows = agent.get("windows", {})
        for window_name in WINDOW_ORDER[agent_name]:
            window = windows.get(window_name) if isinstance(windows, dict) else None
            if not isinstance(window, dict):
                continue
            used = window.get("used_percent")
            used_text = f"{used:>3.0f}%" if isinstance(used, (int, float)) else "  -"
            label = WINDOW_SHORT_LABELS.get(window_name, window_name)
            reset_text = format_reset_compact(window.get("reset_at"), reference)
            lines.append(f"{label} {render_bar(used)} {used_text} · {reset_text}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def action_load_settings(_: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    return {
        "ok": True,
        "settings": {
            **settings,
            "has_token": has_token(),
            "thresholds": THRESHOLDS,
        },
    }


def action_save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    settings["enabled"] = bool(payload.get("enabled", settings.get("enabled", False)))
    settings["chat_id"] = payload.get("chat_id", settings.get("chat_id"))
    settings["chat_label"] = payload.get("chat_label", settings.get("chat_label"))
    token = payload.get("bot_token")
    if isinstance(token, str):
        token = token.strip()
        if token:
            save_token(token)
        elif payload.get("clear_token"):
            delete_token()
    elif payload.get("clear_token"):
        delete_token()
    save_settings(settings)
    return {
        "ok": True,
        "settings": {
            **settings,
            "has_token": has_token(),
            "thresholds": THRESHOLDS,
        },
    }


def action_discover_chat(_: dict[str, Any]) -> dict[str, Any]:
    token = load_token()
    if not token:
        raise RuntimeError("Save the Telegram bot token first.")
    updates = telegram_api(token, "getUpdates", {"timeout": "1", "limit": "20"})
    result = updates.get("result", [])
    chosen = None
    for item in reversed(result):
        for key in ("message", "edited_message", "channel_post"):
            message = item.get(key)
            if not isinstance(message, dict):
                continue
            chat = message.get("chat")
            if isinstance(chat, dict) and chat.get("id") is not None:
                chosen = chat
                break
        if chosen:
            break
    if not chosen:
        raise RuntimeError("No recent Telegram chat found. Open the bot and press Start first.")
    settings = load_settings()
    settings["chat_id"] = str(chosen.get("id"))
    title = chosen.get("title") or chosen.get("username") or chosen.get("first_name") or str(chosen.get("id"))
    settings["chat_label"] = str(title)
    save_settings(settings)
    return {"ok": True, "chat_id": settings["chat_id"], "chat_label": settings["chat_label"]}


def action_send_test(payload: dict[str, Any]) -> dict[str, Any]:
    token = load_token()
    if not token:
        raise RuntimeError("Save the Telegram bot token first.")
    settings = load_settings()
    chat_id = settings.get("chat_id")
    if not chat_id:
        raise RuntimeError("Find your Telegram chat first.")
    send_message(
        token,
        str(chat_id),
        "\n".join(
            [
                "✅ UsageTray 測試訊息",
                "Telegram 通知已連線。",
                f"時間：{format_stamp(payload.get('captured_at') or dt.datetime.now().astimezone().isoformat())}",
            ]
        ),
    )
    return {"ok": True}


def action_process_alerts(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    if not settings.get("enabled"):
        return {"ok": True, "sent": 0, "reason": "disabled"}
    token = load_token()
    chat_id = settings.get("chat_id")
    if not token or not chat_id:
        return {"ok": True, "sent": 0, "reason": "not_configured"}

    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    if not isinstance(snapshot, dict):
        raise RuntimeError("Invalid alert payload.")

    state = load_state()
    threshold_state = state.setdefault("thresholds", {})
    error_state = state.setdefault("errors", {})
    sent = 0
    crossings: list[dict[str, Any]] = []

    agents = snapshot.get("agents", {})
    if not isinstance(agents, dict):
        return {"ok": True, "sent": 0, "reason": "no_agents"}

    for agent_name, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        if agent.get("available") is False:
            error = agent.get("error") or {}
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                if isinstance(code, str) and error_state.get(agent_name) != code:
                    send_message(
                        token,
                        str(chat_id),
                        error_message(snapshot, str(agent_name), code, message if isinstance(message, str) else None),
                        parse_mode="MarkdownV2",
                    )
                    error_state[agent_name] = code
                    sent += 1
            continue

        error_state.pop(agent_name, None)
        windows = agent.get("windows", {})
        if not isinstance(windows, dict):
            continue
        for window_name, window in windows.items():
            if not isinstance(window, dict):
                continue
            used = window.get("used_percent")
            remaining = window.get("remaining_percent")
            if not isinstance(used, (int, float)) or not isinstance(remaining, (int, float)):
                continue
            key = f"{agent_name}:{window_name}"
            cycle = alert_cycle_id(window)
            slot = threshold_state.get(key)
            if isinstance(slot, dict) and same_cycle(slot.get("cycle"), cycle):
                # Same cycle (allowing reset_at jitter): track the latest id so
                # slow drift never accumulates past the tolerance.
                slot["cycle"] = cycle
            else:
                # New cycle (or first sight of this window): start empty and fall
                # through so thresholds already crossed still notify once.
                slot = {"cycle": cycle, "sent": []}
                threshold_state[key] = slot
            sent_marks = slot.get("sent")
            if not isinstance(sent_marks, list):
                sent_marks = []
                slot["sent"] = sent_marks
            pending = [
                threshold
                for threshold in reached_thresholds(float(used))
                if threshold not in sent_marks
            ]
            if pending:
                crossings.append(
                    {
                        "agent": str(agent_name),
                        "window_name": str(window_name),
                        "used": float(used),
                        "remaining": float(remaining),
                        "reset_at": window.get("reset_at"),
                        "threshold": max(pending),
                        "pending": pending,
                        "sent_marks": sent_marks,
                    }
                )

    if crossings:
        # All windows that crossed a threshold in this run share one message.
        send_message(
            token,
            str(chat_id),
            alert_message(snapshot, crossings),
            parse_mode="MarkdownV2",
        )
        for crossing in crossings:
            crossing["sent_marks"].extend(crossing["pending"])
        sent += 1

    save_state(state)
    return {"ok": True, "sent": sent}


def is_usage_command(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    return stripped == "/usage" or stripped.startswith("/usage@")


def action_poll_commands(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    if not settings.get("enabled"):
        return {"ok": True, "handled": 0, "reason": "disabled"}
    token = load_token()
    chat_id = settings.get("chat_id")
    if not token or chat_id is None:
        return {"ok": True, "handled": 0, "reason": "not_configured"}

    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    if not isinstance(snapshot, dict):
        raise RuntimeError("Invalid command payload.")

    state = load_updates_state()
    try:
        updates = telegram_api(
            token,
            "getUpdates",
            {"offset": str(state["last_update_id"] + 1), "timeout": "0"},
        )
    except Exception:  # noqa: BLE001
        return {"ok": True, "handled": 0, "reason": "poll_failed"}

    result = updates.get("result", [])
    if not isinstance(result, list):
        result = []

    should_reply = False
    for update in result:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            state["last_update_id"] = max(state["last_update_id"], update_id)
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict):
            continue
        if str(chat.get("id")) != str(chat_id):
            continue
        if is_usage_command(message.get("text")):
            should_reply = True

    save_updates_state(state)
    if should_reply:
        send_message(
            token,
            str(chat_id),
            usage_command_message(snapshot),
            parse_mode="MarkdownV2",
        )
        return {"ok": True, "handled": 1}
    return {"ok": True, "handled": 0}


ACTIONS = {
    "load-settings": action_load_settings,
    "save-settings": action_save_settings,
    "discover-chat": action_discover_chat,
    "send-test": action_send_test,
    "process-alerts": action_process_alerts,
    "poll-commands": action_poll_commands,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        sys.stderr.write("Usage: telegram_bridge.py <action>\n")
        return 2
    action = sys.argv[1]
    try:
        payload = read_json_stdin()
        result = ACTIONS[action](payload)
    except Exception as error:  # noqa: BLE001
        write_json_stdout({"ok": False, "error": str(error)})
        return 1
    write_json_stdout(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
