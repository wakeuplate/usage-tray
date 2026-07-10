#!/usr/bin/env python3
"""Sanitize collector output into history snapshots.

This module is intentionally small: it does not call Codex, Claude, or any
network endpoint. It only accepts collector JSON that already exists and writes
safe JSONL snapshots when asked.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


SNAPSHOT_SCHEMA_VERSION = "usage-tray.snapshot.v0"
DEFAULT_MIN_INTERVAL_SEC = 300
SAFE_AGENT_KEYS = {"available", "source", "captured_at", "error", "windows"}
SAFE_WINDOW_KEYS = {
    "name",
    "used_percent",
    "remaining_percent",
    "reset_at",
    "reset_at_unix",
    "window_duration_mins",
}


def safe_error(error: Any) -> dict[str, Any] | None:
    if not isinstance(error, dict):
        return None
    return {"code": error.get("code")}


def safe_window(window: Any) -> dict[str, Any]:
    if not isinstance(window, dict):
        return {}
    return {key: window.get(key) for key in SAFE_WINDOW_KEYS}


def safe_windows(windows: Any) -> dict[str, Any]:
    if not isinstance(windows, dict):
        return {}
    return {name: safe_window(window) for name, window in windows.items()}


def safe_agent(agent: Any) -> dict[str, Any]:
    if not isinstance(agent, dict):
        return {
            "available": False,
            "source": "unknown",
            "error": {"code": "invalid_agent", "message": "Agent payload was not an object."},
            "windows": {},
        }

    safe: dict[str, Any] = {}
    for key in SAFE_AGENT_KEYS:
        if key not in agent:
            continue
        if key == "error":
            safe[key] = safe_error(agent.get(key))
        elif key == "windows":
            safe[key] = safe_windows(agent.get(key))
        else:
            safe[key] = agent.get(key)

    safe.setdefault("available", False)
    safe.setdefault("source", "unknown")
    safe.setdefault("error", None)
    safe.setdefault("windows", {})
    return safe


def sanitize_collector_snapshot(collector_payload: dict[str, Any]) -> dict[str, Any]:
    agents = collector_payload.get("agents") if isinstance(collector_payload.get("agents"), dict) else {}
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "collector_schema_version": collector_payload.get("schema_version"),
        "captured_at": collector_payload.get("captured_at"),
        "agents": {name: safe_agent(agent) for name, agent in agents.items()},
    }


def append_snapshot(output_path: Path, snapshot: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    needs_newline = False
    if output_path.exists() and output_path.stat().st_size > 0:
        with output_path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            needs_newline = existing.read(1) not in {b"\n", b"\r"}

    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        if needs_newline:
            handle.write("\n")
        handle.write(line + "\n")


def read_latest_snapshot(output_path: Path) -> dict[str, Any] | None:
    if not output_path.exists() or output_path.stat().st_size == 0:
        return None

    with output_path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        buffer = b""

        while position > 0:
            chunk_size = min(4096, position)
            position -= chunk_size
            handle.seek(position)
            buffer = handle.read(chunk_size) + buffer
            stripped = buffer.rstrip(b"\r\n")

            if position == 0 or b"\n" in stripped:
                line = stripped.rsplit(b"\n", 1)[-1].strip()
                if not line:
                    return None
                try:
                    loaded = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                return loaded if isinstance(loaded, dict) else None

    return None


def visible_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    agents = snapshot.get("agents")
    state: dict[str, Any] = {}
    if not isinstance(agents, dict):
        return state

    for agent_name, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        windows = agent.get("windows")
        visible_windows: dict[str, Any] = {}
        if isinstance(windows, dict):
            for window_name, window in windows.items():
                if not isinstance(window, dict):
                    continue
                visible_windows[window_name] = {
                    "used_percent": round(window.get("used_percent"))
                    if isinstance(window.get("used_percent"), (int, float))
                    else None,
                    "remaining_percent": round(window.get("remaining_percent"))
                    if isinstance(window.get("remaining_percent"), (int, float))
                    else None,
                    "reset_at": window.get("reset_at"),
                    "window_duration_mins": window.get("window_duration_mins"),
                }

        error = agent.get("error")
        state[agent_name] = {
            "available": agent.get("available"),
            "source": agent.get("source"),
            "error_code": error.get("code") if isinstance(error, dict) else None,
            "windows": visible_windows,
        }

    return state


def append_snapshot_if_needed(
    output_path: Path,
    snapshot: dict[str, Any],
    min_interval_sec: int = DEFAULT_MIN_INTERVAL_SEC,
    now: float | None = None,
) -> bool:
    latest = read_latest_snapshot(output_path)
    current_time = time.time() if now is None else now

    if latest is not None and visible_state(latest) == visible_state(snapshot):
        age_sec = max(0.0, current_time - output_path.stat().st_mtime)
        if age_sec < min_interval_sec:
            return False

    append_snapshot(output_path, snapshot)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write sanitized UsageTray snapshot JSONL.")
    parser.add_argument("--input", help="Collector JSON file. Reads stdin when omitted.")
    parser.add_argument("--output", required=True, help="JSONL output path.")
    parser.add_argument(
        "--min-interval-sec",
        type=int,
        default=DEFAULT_MIN_INTERVAL_SEC,
        help="Write unchanged readings at most once per interval.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        payload = json.loads(sys.stdin.read())

    snapshot = sanitize_collector_snapshot(payload)
    append_snapshot_if_needed(
        Path(args.output),
        snapshot,
        min_interval_sec=max(0, args.min_interval_sec),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
