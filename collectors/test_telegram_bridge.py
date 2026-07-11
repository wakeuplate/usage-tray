#!/usr/bin/env python3
"""Focused checks for the Telegram error-alert de-duplication.

A data-source outage should notify once, then stay quiet until the agent
recovers - even if the underlying error code keeps changing (e.g. an expired
token returning 401 one cycle and a rate-limit 429 the next). Only a recovery
resets the notification.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


TELEGRAM_PATH = Path(__file__).with_name("telegram_bridge.py")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def outage_snapshot(code: str | None) -> dict[str, Any]:
    return {
        "captured_at": "2026-07-10T10:00:00Z",
        "agents": {
            "claude": {
                "available": False,
                "error": {"code": code, "message": "source unavailable"},
                "windows": {},
            }
        },
    }


def healthy_snapshot() -> dict[str, Any]:
    return {
        "captured_at": "2026-07-10T10:05:00Z",
        "agents": {
            "claude": {
                "available": True,
                "windows": {
                    "five_hour": {
                        "used_percent": 10.0,
                        "remaining_percent": 90.0,
                        "reset_at": "2026-07-10T14:00:00Z",
                        "window_duration_mins": 300,
                    }
                },
            }
        },
    }


class TelegramErrorDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.telegram = load_module("telegram_bridge", TELEGRAM_PATH)

    def _run(self, tmp_dir: str, sent: list[str], snapshot: dict[str, Any]) -> dict[str, Any]:
        with mock.patch.object(self.telegram, "app_dir", return_value=Path(tmp_dir)), mock.patch.object(
            self.telegram, "load_settings", return_value={"enabled": True, "chat_id": "12345"}
        ), mock.patch.object(self.telegram, "load_token", return_value="token"), mock.patch.object(
            self.telegram, "send_message", side_effect=lambda _t, _c, text, parse_mode=None: sent.append(text)
        ):
            return self.telegram.action_process_alerts({"snapshot": snapshot})

    def test_alternating_error_codes_notify_once_per_outage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sent: list[str] = []

            first = self._run(tmp_dir, sent, outage_snapshot("claude_auth_expired"))
            # Same outage, error code flips 401 -> 429 -> 401: must stay quiet.
            second = self._run(tmp_dir, sent, outage_snapshot("claude_rate_limited"))
            third = self._run(tmp_dir, sent, outage_snapshot("claude_auth_expired"))

            self.assertEqual(first, {"ok": True, "sent": 1})
            self.assertEqual(second, {"ok": True, "sent": 0})
            self.assertEqual(third, {"ok": True, "sent": 0})
            self.assertEqual(len(sent), 1)

            state = json.loads((Path(tmp_dir) / "telegram-alert-state.json").read_text(encoding="utf-8"))
            self.assertIn("claude", state["errors"])

    def test_recovery_resets_and_new_outage_notifies_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sent: list[str] = []

            first = self._run(tmp_dir, sent, outage_snapshot("claude_auth_expired"))
            recovered = self._run(tmp_dir, sent, healthy_snapshot())
            # A fresh outage after recovery must notify again.
            second = self._run(tmp_dir, sent, outage_snapshot("claude_auth_expired"))

            self.assertEqual(first, {"ok": True, "sent": 1})
            self.assertEqual(recovered, {"ok": True, "sent": 0})
            self.assertEqual(second, {"ok": True, "sent": 1})
            self.assertEqual(len(sent), 2)

            state = json.loads((Path(tmp_dir) / "telegram-alert-state.json").read_text(encoding="utf-8"))
            self.assertIn("claude", state["errors"])

    def test_recovery_clears_error_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sent: list[str] = []

            self._run(tmp_dir, sent, outage_snapshot("claude_auth_expired"))
            self._run(tmp_dir, sent, healthy_snapshot())

            state = json.loads((Path(tmp_dir) / "telegram-alert-state.json").read_text(encoding="utf-8"))
            self.assertNotIn("claude", state["errors"])


class TelegramCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.telegram = load_module("telegram_bridge_commands", TELEGRAM_PATH)

    def test_command_name_accepts_refresh_commands_with_bot_suffix(self) -> None:
        self.assertEqual(self.telegram.command_name("/refresh_claude@usage_bot"), "/refresh_claude")
        self.assertEqual(self.telegram.command_name("/refresh_codex extra words"), "/refresh_codex")
        self.assertIsNone(self.telegram.command_name("/refresh_everything"))

    def test_refresh_message_reports_only_requested_agent(self) -> None:
        message = self.telegram.refresh_command_message(healthy_snapshot(), "claude")
        self.assertIn("Claude", message)
        self.assertNotIn("Codex", message)

    def test_refresh_command_from_other_chat_is_ignored(self) -> None:
        updates = {
            "result": [
                {
                    "update_id": 100,
                    "message": {"chat": {"id": "other"}, "text": "/refresh_claude"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch.object(
            self.telegram, "app_dir", return_value=Path(tmp_dir)
        ), mock.patch.object(
            self.telegram, "load_settings", return_value={"enabled": True, "chat_id": "allowed"}
        ), mock.patch.object(self.telegram, "load_token", return_value="token"), mock.patch.object(
            self.telegram, "telegram_api", return_value=updates
        ), mock.patch.object(self.telegram, "send_message") as send_message:
            result = self.telegram.action_poll_commands({"snapshot": healthy_snapshot()})
        self.assertEqual(result, {"ok": True, "handled": 0})
        send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
