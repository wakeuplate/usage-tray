#!/usr/bin/env python3
"""Minimal Limit Lens datasource collector.

The collector prints sanitized JSON to stdout. It never prints bearer
credentials and only refreshes Claude OAuth tokens when needed.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "limit-lens.collector.v0"
CLAUDE_USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_REFRESH_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
CLAUDE_REFRESH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_BETA = "oauth-2025-04-20"
CLAUDE_USER_AGENT = "claude-code/2.1.199"
CLAUDE_REFRESH_BUFFER_MS = 300_000
REFRESH_COOLDOWN_MS = 600_000


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def unix_seconds_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def millis_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def source_error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def claude_http_error(code: int, reason: str) -> dict[str, str]:
    if code == 401:
        return source_error(
            "claude_auth_expired",
            "Claude Code sign-in expired. Run claude auth login.",
        )
    return source_error("claude_http_error", f"HTTP {code}: {reason}")


def redact_tokens(message: str, *tokens: str | None) -> str:
    redacted = message
    for token in tokens:
        if token:
            redacted = redacted.replace(token, "<token redacted>")
    return redacted


def parse_json_body(body: bytes) -> tuple[Any, list[str] | None, str | None]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None, None, "non_json"
    if isinstance(payload, dict):
        return payload, sorted(payload.keys()), "dict"
    if isinstance(payload, list):
        return payload, None, "list"
    return payload, None, type(payload).__name__


def load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_name(f"{path.name}.usagetray-tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def default_refresh_state_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "UsageTray" / "claude-refresh-state.json"


def resolve_refresh_state_path(refresh_state_file: str | None) -> Path | None:
    if refresh_state_file:
        return Path(refresh_state_file)
    return default_refresh_state_path()


def load_refresh_state(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        state = load_json_file(path)
    except Exception:  # noqa: BLE001 - cooldown is advisory.
        return None
    if not isinstance(state, dict):
        return None
    last_failed_attempt_ms = state.get("last_failed_attempt_ms")
    last_status = state.get("last_status")
    if not isinstance(last_failed_attempt_ms, int) or isinstance(last_failed_attempt_ms, bool):
        return None
    if not isinstance(last_status, (int, str)) or isinstance(last_status, bool):
        return None
    return {
        "last_failed_attempt_ms": last_failed_attempt_ms,
        "last_status": last_status,
    }


def refresh_cooldown_active(path: Path | None, now_ms: int) -> bool:
    state = load_refresh_state(path)
    if state is None:
        return False
    return now_ms - int(state["last_failed_attempt_ms"]) < REFRESH_COOLDOWN_MS


def write_refresh_state(path: Path | None, last_failed_attempt_ms: int, last_status: int | str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        path,
        {
            "last_failed_attempt_ms": last_failed_attempt_ms,
            "last_status": last_status,
        },
    )


def clear_refresh_state(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - cooldown cleanup must not break collection.
        pass


def request_claude_refresh(refresh_token: str, timeout_sec: int, scopes: list[str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLAUDE_REFRESH_CLIENT_ID,
    }
    if scopes:
        body["scope"] = " ".join(scopes)
    request = urllib.request.Request(
        CLAUDE_REFRESH_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": CLAUDE_USER_AGENT,
            "anthropic-beta": CLAUDE_BETA,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Claude refresh response must be a JSON object.")
    return payload


def fetch_claude_usage(access_token: str, timeout_sec: int) -> dict[str, Any]:
    request = urllib.request.Request(
        CLAUDE_USAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": CLAUDE_USER_AGENT,
            "anthropic-beta": CLAUDE_BETA,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Claude usage response must be a JSON object.")
    return payload


def refresh_claude_credentials(
    path: Path,
    credentials: dict[str, Any],
    oauth: dict[str, Any],
    started_access_token: str,
    timeout_sec: int,
    now_ms: int,
    refresh_state_path: Path | None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    refresh_token = oauth.get("refreshToken")
    if not isinstance(refresh_token, str) or not refresh_token:
        return started_access_token, None, {}

    diagnostics: dict[str, Any] = {}
    try:
        scopes = oauth.get("scopes") if isinstance(oauth.get("scopes"), list) else None
        payload = request_claude_refresh(refresh_token, timeout_sec, scopes)
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        _, body_keys, body_type = parse_json_body(body or b"")
        diagnostics["refresh_status"] = exc.code
        if body_keys is not None:
            diagnostics["refresh_body_keys"] = body_keys
        diagnostics["refresh_body_type"] = body_type
        try:
            write_refresh_state(refresh_state_path, now_ms, exc.code)
        except Exception:  # noqa: BLE001 - refresh failure must not break collection.
            diagnostics["cooldown_write_failed"] = True
        return started_access_token, None, {
            "error": source_error(
                "claude_refresh_failed",
                f"HTTP {exc.code}: {exc.reason}",
            ),
            "diagnostics": diagnostics,
        }
    except Exception as exc:  # noqa: BLE001 - collector returns JSON errors.
        diagnostics["refresh_body_type"] = type(exc).__name__
        try:
            write_refresh_state(refresh_state_path, now_ms, type(exc).__name__)
        except Exception:  # noqa: BLE001 - refresh failure must not break collection.
            diagnostics["cooldown_write_failed"] = True
        return started_access_token, None, {
            "error": source_error("claude_refresh_failed", f"HTTP 0: {type(exc).__name__}"),
            "diagnostics": diagnostics,
        }

    new_access_token = payload.get("access_token")
    if not isinstance(new_access_token, str) or not new_access_token:
        diagnostics["refresh_response_keys"] = sorted(payload.keys())
        try:
            write_refresh_state(refresh_state_path, now_ms, "missing_access_token")
        except Exception:  # noqa: BLE001 - refresh failure must not break collection.
            diagnostics["cooldown_write_failed"] = True
        return started_access_token, None, {
            "error": source_error("claude_refresh_failed", "HTTP 200: invalid refresh response"),
            "diagnostics": diagnostics,
        }

    expires_in = payload.get("expires_in")
    try:
        expires_delta_ms = int(float(expires_in)) * 1000
    except (TypeError, ValueError):
        diagnostics["refresh_response_keys"] = sorted(payload.keys())
        try:
            write_refresh_state(refresh_state_path, now_ms, "invalid_expires_in")
        except Exception:  # noqa: BLE001 - refresh failure must not break collection.
            diagnostics["cooldown_write_failed"] = True
        return started_access_token, None, {
            "error": source_error("claude_refresh_failed", "HTTP 200: invalid refresh response"),
            "diagnostics": diagnostics,
        }

    clear_refresh_state(refresh_state_path)

    try:
        current_credentials = load_json_file(path)
        current_oauth = current_credentials.get("claudeAiOauth")
        if not isinstance(current_oauth, dict):
            diagnostics["current_root_keys"] = sorted(current_credentials.keys())
            raise ValueError("invalid credential shape")
    except Exception as exc:  # noqa: BLE001 - collector returns JSON errors.
        diagnostics["token_refreshed"] = True
        diagnostics["refresh_writeback_failed"] = True
        diagnostics["refresh_writeback_error_type"] = type(exc).__name__
        return new_access_token, credentials, {
            "warning": "claude_refresh_writeback_failed",
            "diagnostics": diagnostics,
        }

    current_access_token = current_oauth.get("accessToken")
    diagnostics["token_refreshed"] = True
    if current_access_token != started_access_token:
        return (
            current_access_token if isinstance(current_access_token, str) and current_access_token else started_access_token,
            current_credentials,
            {"diagnostics": diagnostics},
        )

    updated_credentials = dict(credentials)
    updated_oauth = dict(oauth)
    updated_oauth["accessToken"] = new_access_token
    updated_oauth["refreshToken"] = payload.get("refresh_token") if isinstance(payload.get("refresh_token"), str) and payload.get("refresh_token") else refresh_token
    updated_oauth["expiresAt"] = now_ms + expires_delta_ms
    updated_credentials["claudeAiOauth"] = updated_oauth

    try:
        write_json_atomic(path, updated_credentials)
    except Exception as exc:  # noqa: BLE001 - collector returns JSON errors.
        diagnostics["token_refreshed"] = True
        diagnostics["refresh_writeback_failed"] = True
        diagnostics["refresh_writeback_error_type"] = type(exc).__name__
        return new_access_token, current_credentials, {
            "warning": "claude_refresh_writeback_failed",
            "diagnostics": diagnostics,
        }

    return new_access_token, updated_credentials, {"diagnostics": diagnostics}


def usage_window(
    name: str,
    used_percent: Any,
    reset_at: Any,
    window_duration_mins: int | None,
    reset_kind: str = "iso8601",
) -> dict[str, Any]:
    used = None if used_percent is None else float(used_percent)
    remaining = None if used is None else max(0.0, min(100.0, 100.0 - used))
    reset_unix = None
    reset_iso = None
    if reset_kind == "unix_seconds":
        reset_unix = None if reset_at is None else int(reset_at)
        reset_iso = unix_seconds_to_iso(reset_at)
    else:
        reset_iso = None if reset_at is None else str(reset_at)
    return {
        "name": name,
        "used_percent": used,
        "remaining_percent": remaining,
        "reset_at": reset_iso,
        "reset_at_unix": reset_unix,
        "window_duration_mins": window_duration_mins,
    }


def write_json_line(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if proc.stdin is None:
        raise RuntimeError("process stdin unavailable")
    proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def start_reader(stream: Any) -> queue.Queue[str]:
    lines: queue.Queue[str] = queue.Queue()

    def read() -> None:
        try:
            for line in stream:
                lines.put(line.rstrip("\n"))
        finally:
            lines.put("__LIMIT_LENS_EOF__")

    threading.Thread(target=read, daemon=True).start()
    return lines


def wait_for_response(
    proc: subprocess.Popen[str],
    lines: queue.Queue[str],
    request_id: int,
    deadline: float,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue

        if line == "__LIMIT_LENS_EOF__":
            break
        if not line.strip():
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            seen.append({"non_json_prefix": line[:120]})
            continue

        seen.append(
            {
                "id": payload.get("id"),
                "method": payload.get("method"),
                "keys": sorted(payload.keys()),
            }
        )
        if payload.get("id") == request_id:
            return payload, seen

    return None, seen


def hidden_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {"creationflags": flags, "startupinfo": startupinfo}


def collect_codex(codex_command: str, timeout_sec: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "source": "codex_app_server",
        "command": codex_command,
        "captured_at": iso_now(),
        "error": None,
        "diagnostics": {},
        "windows": {},
    }

    if not Path(codex_command).is_file():
        result["error"] = source_error("codex_command_not_found", f"Codex command not found: {codex_command}")
        return result

    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            [codex_command, "app-server", "--disable", "plugins"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            **hidden_subprocess_kwargs(),
        )
        if proc.stdout is None:
            raise RuntimeError("process stdout unavailable")
        lines = start_reader(proc.stdout)
        deadline = time.monotonic() + timeout_sec

        write_json_line(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "usage-tray-collector",
                        "title": "UsageTray Collector",
                        "version": "0.0.1",
                    },
                    "capabilities": {},
                },
            },
        )
        init, init_seen = wait_for_response(proc, lines, 1, deadline)
        if init is None:
            result["error"] = source_error("codex_initialize_timeout", "Timed out waiting for initialize response.")
            result["diagnostics"]["seen"] = init_seen
            return result
        if init.get("error"):
            result["error"] = source_error("codex_initialize_error", str(init["error"].get("message")))
            result["diagnostics"]["error_code"] = init["error"].get("code")
            return result

        init_result = init.get("result") or {}
        result["diagnostics"]["initialize_result_keys"] = sorted(init_result.keys())
        result["diagnostics"]["codex_home"] = init_result.get("codexHome")
        result["diagnostics"]["user_agent"] = init_result.get("userAgent")

        write_json_line(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        write_json_line(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "account/rateLimits/read",
                "params": {},
            },
        )

        response, seen = wait_for_response(proc, lines, 2, deadline)
        result["diagnostics"]["seen"] = seen
        if response is None:
            result["error"] = source_error("codex_rate_limits_timeout", "Timed out waiting for rate limit response.")
            return result
        if response.get("error"):
            result["error"] = source_error("codex_rate_limits_error", str(response["error"].get("message")))
            result["diagnostics"]["error_code"] = response["error"].get("code")
            return result

        payload = response.get("result") or {}
        rate_limits = payload.get("rateLimits") or {}
        primary = rate_limits.get("primary") or {}
        secondary = rate_limits.get("secondary") or {}

        result["available"] = True
        result["diagnostics"]["result_keys"] = sorted(payload.keys())
        result["diagnostics"]["rate_limit_keys"] = sorted(rate_limits.keys())
        result["diagnostics"]["plan_type"] = rate_limits.get("planType")
        result["diagnostics"]["limit_name"] = rate_limits.get("limitName")
        result["diagnostics"]["rate_limit_reached_type"] = rate_limits.get("rateLimitReachedType")
        credits = rate_limits.get("credits")
        if isinstance(credits, dict):
            result["diagnostics"]["credits"] = {
                "has_credits": credits.get("hasCredits"),
                "unlimited": credits.get("unlimited"),
            }

        result["windows"]["five_hour"] = usage_window(
            "primary",
            primary.get("usedPercent"),
            primary.get("resetsAt"),
            primary.get("windowDurationMins"),
            "unix_seconds",
        )
        result["windows"]["weekly"] = usage_window(
            "secondary",
            secondary.get("usedPercent"),
            secondary.get("resetsAt"),
            secondary.get("windowDurationMins"),
            "unix_seconds",
        )
    except Exception as exc:  # noqa: BLE001 - collector returns JSON errors.
        result["error"] = source_error("codex_collector_exception", str(exc))
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    return result


def collect_claude(credentials_path: str, timeout_sec: int, refresh_state_file: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "source": "claude_code_oauth",
        "credential_path": credentials_path,
        "captured_at": iso_now(),
        "error": None,
        "diagnostics": {},
        "windows": {},
        "limits": [],
        "spend": None,
    }

    path = Path(credentials_path)
    if not path.is_file():
        result["error"] = source_error("claude_credentials_not_found", f"Claude credentials not found: {credentials_path}")
        return result

    refresh_state_path = resolve_refresh_state_path(refresh_state_file)
    access_token: str | None = None
    refresh_token: str | None = None
    try:
        credentials = load_json_file(path)
        oauth = credentials.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            result["error"] = source_error("claude_oauth_missing", "claudeAiOauth object not found.")
            result["diagnostics"]["root_keys"] = sorted(credentials.keys())
            return result

        access_token = oauth.get("accessToken")
        if not access_token:
            result["error"] = source_error("claude_access_token_missing", "claudeAiOauth.accessToken is missing.")
            return result
        refresh_token = oauth.get("refreshToken") if isinstance(oauth.get("refreshToken"), str) else None

        result["diagnostics"]["root_keys"] = sorted(credentials.keys())
        result["diagnostics"]["oauth_keys"] = sorted(oauth.keys())
        result["diagnostics"]["expires_at"] = millis_to_iso(oauth.get("expiresAt"))
        scopes = oauth.get("scopes") if isinstance(oauth.get("scopes"), list) else []
        result["diagnostics"]["scopes_count"] = len(scopes)
        result["diagnostics"]["subscription_type_present"] = bool(oauth.get("subscriptionType"))
        result["diagnostics"]["rate_limit_tier_present"] = bool(oauth.get("rateLimitTier"))
        now_ms = int(time.time() * 1000)
        expires_at = oauth.get("expiresAt")
        should_refresh = (
            isinstance(refresh_token, str)
            and refresh_token
            and (
                expires_at is None
                or not isinstance(expires_at, (int, float))
                or now_ms >= int(expires_at) - CLAUDE_REFRESH_BUFFER_MS
            )
        )
        refreshed = False
        refresh_result: dict[str, Any] | None = None
        current_credentials = credentials
        if should_refresh:
            if refresh_cooldown_active(refresh_state_path, now_ms):
                result["diagnostics"]["refresh_cooldown_active"] = True
                result["error"] = source_error(
                    "claude_refresh_cooldown",
                    "Refresh recently failed; retrying after cooldown.",
                )
                return result
            access_token, current_credentials, refresh_result = refresh_claude_credentials(
                path,
                credentials,
                oauth,
                access_token,
                timeout_sec,
                now_ms,
                refresh_state_path,
            )
            if refresh_result:
                result["diagnostics"].update(refresh_result.get("diagnostics") or {})
                warning = refresh_result.get("warning")
                if warning:
                    result["diagnostics"]["warning"] = warning
                if refresh_result.get("error"):
                    result["error"] = refresh_result["error"]
                    result["available"] = False
                    return result
                refreshed = bool(result["diagnostics"].get("token_refreshed"))

        payload: dict[str, Any] | None = None
        usage_error: urllib.error.HTTPError | None = None
        try:
            payload = fetch_claude_usage(access_token, timeout_sec)
        except urllib.error.HTTPError as exc:
            usage_error = exc

        if usage_error and usage_error.code == 401 and not refreshed:
            if refresh_cooldown_active(refresh_state_path, now_ms):
                result["diagnostics"]["refresh_cooldown_active"] = True
            else:
                refreshed_access_token, refreshed_credentials, refresh_result = refresh_claude_credentials(
                    path,
                    credentials,
                    oauth,
                    access_token,
                    timeout_sec,
                    now_ms,
                    refresh_state_path,
                )
                if refresh_result:
                    result["diagnostics"].update(refresh_result.get("diagnostics") or {})
                    warning = refresh_result.get("warning")
                    if warning:
                        result["diagnostics"]["warning"] = warning
                    if refresh_result.get("error"):
                        result["error"] = refresh_result["error"]
                        result["available"] = False
                        return result
                    refreshed = bool(result["diagnostics"].get("token_refreshed"))
                    access_token = refreshed_access_token
                try:
                    payload = fetch_claude_usage(access_token, timeout_sec)
                    usage_error = None
                except urllib.error.HTTPError as exc:
                    usage_error = exc

        if usage_error is not None:
            result["error"] = claude_http_error(usage_error.code, str(usage_error.reason))
            return result
        if payload is None:
            result["error"] = source_error("claude_collector_exception", "Claude usage response missing.")
            return result

        result["available"] = True
        result["diagnostics"]["top_level_keys"] = sorted(payload.keys())

        five_hour = payload.get("five_hour") or {}
        seven_day = payload.get("seven_day") or {}
        if five_hour:
            result["windows"]["five_hour"] = usage_window(
                "five_hour",
                five_hour.get("utilization"),
                five_hour.get("resets_at"),
                300,
            )
        if seven_day:
            result["windows"]["weekly"] = usage_window(
                "seven_day",
                seven_day.get("utilization"),
                seven_day.get("resets_at"),
                10080,
            )

        limits: list[dict[str, Any]] = []
        for limit in payload.get("limits") or []:
            scope = None
            raw_scope = limit.get("scope")
            if isinstance(raw_scope, dict):
                model = raw_scope.get("model") if isinstance(raw_scope.get("model"), dict) else {}
                scope = {
                    "model_display_name_present": bool(model.get("display_name")),
                    "surface_present": bool(raw_scope.get("surface")),
                }
            limits.append(
                {
                    "kind": limit.get("kind"),
                    "group": limit.get("group"),
                    "percent": limit.get("percent"),
                    "severity": limit.get("severity"),
                    "resets_at": limit.get("resets_at"),
                    "is_active": limit.get("is_active"),
                    "scope": scope,
                }
            )
        result["limits"] = limits

        weekly_scoped = next((limit for limit in limits if limit.get("kind") == "weekly_scoped"), None)
        if weekly_scoped:
            result["windows"]["weekly_scoped"] = usage_window(
                "weekly_scoped",
                weekly_scoped.get("percent"),
                weekly_scoped.get("resets_at"),
                10080,
            )

        spend = payload.get("spend")
        if isinstance(spend, dict):
            used = spend.get("used") if isinstance(spend.get("used"), dict) else {}
            result["spend"] = {
                "percent": spend.get("percent"),
                "severity": spend.get("severity"),
                "enabled": spend.get("enabled"),
                "currency": used.get("currency"),
                "used_amount_minor": used.get("amount_minor"),
                "exponent": used.get("exponent"),
            }
    except urllib.error.HTTPError as exc:
        result["error"] = claude_http_error(exc.code, str(exc.reason))
    except Exception as exc:  # noqa: BLE001 - collector returns JSON errors.
        message = str(exc)
        message = redact_tokens(message, access_token, refresh_token)
        result["error"] = source_error("claude_collector_exception", message)

    return result


def parse_args() -> argparse.Namespace:
    default_codex = str(Path(os.environ.get("APPDATA", "")) / "npm" / "codex.cmd")
    default_claude = str(Path.home() / ".claude" / ".credentials.json")
    default_refresh_state = default_refresh_state_path()
    parser = argparse.ArgumentParser(description="Collect sanitized Limit Lens datasource snapshots.")
    parser.add_argument("--codex-command", default=default_codex)
    parser.add_argument("--claude-credentials", default=default_claude)
    parser.add_argument("--refresh-state-file", default=str(default_refresh_state) if default_refresh_state else None)
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--skip-codex", action="store_true")
    parser.add_argument("--skip-claude", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": iso_now(),
        "agents": {},
    }

    if not args.skip_codex:
        result["agents"]["codex"] = collect_codex(args.codex_command, args.timeout_sec)
    if not args.skip_claude:
        result["agents"]["claude"] = collect_claude(args.claude_credentials, args.timeout_sec, args.refresh_state_file)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
