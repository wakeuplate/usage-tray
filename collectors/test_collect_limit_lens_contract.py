#!/usr/bin/env python3
"""Small contract checks for the Limit Lens collector.

These tests avoid live Codex/Claude calls. They check the local helper shapes
that the future UI will depend on.
"""

from __future__ import annotations

import io
import importlib.util
import json
import os
import re
import tempfile
import unittest
import urllib.error
from unittest import mock
from pathlib import Path
from typing import Any


COLLECTOR_PATH = Path(__file__).with_name("collect_limit_lens.py")
HISTORY_PATH = Path(__file__).with_name("history_snapshot.py")
PROJECT_ROOT = COLLECTOR_PATH.parent.parent
SAMPLE_PATH = PROJECT_ROOT / "samples" / "collector-output-v0.sample.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "collector-v0.schema.json"
APP_MAIN_PATH = PROJECT_ROOT / "app" / "src" / "main.tsx"
TAURI_LIB_PATH = PROJECT_ROOT / "app" / "src-tauri" / "src" / "lib.rs"
HISTORY_SAMPLE_PATH = PROJECT_ROOT / "app" / "public" / "sample-history-v0.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_window_shape(test_case: unittest.TestCase, window: dict[str, Any]) -> None:
    test_case.assertEqual(
        set(window.keys()),
        {
            "name",
            "used_percent",
            "remaining_percent",
            "reset_at",
            "reset_at_unix",
            "window_duration_mins",
        },
    )
    if window["used_percent"] is not None:
        test_case.assertGreaterEqual(window["used_percent"], 0)
        test_case.assertLessEqual(window["used_percent"], 100)
    if window["remaining_percent"] is not None:
        test_case.assertGreaterEqual(window["remaining_percent"], 0)
        test_case.assertLessEqual(window["remaining_percent"], 100)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def http_error(url: str, code: int, reason: str, body: dict[str, Any] | str) -> urllib.error.HTTPError:
    if isinstance(body, dict):
        body_bytes = json.dumps(body).encode("utf-8")
    else:
        body_bytes = body.encode("utf-8")
    return urllib.error.HTTPError(url, code, reason, hdrs=None, fp=io.BytesIO(body_bytes))


class CollectorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.collector = load_module("collect_limit_lens", COLLECTOR_PATH)
        cls.history = load_module("history_snapshot", HISTORY_PATH)

    def test_schema_version_is_v0(self) -> None:
        self.assertEqual(self.collector.SCHEMA_VERSION, "limit-lens.collector.v0")
        self.assertEqual(self.history.SNAPSHOT_SCHEMA_VERSION, "limit-lens.snapshot.v0")

    def test_usage_window_shape_and_remaining_percent(self) -> None:
        window = self.collector.usage_window(
            "primary",
            31,
            1783952880,
            10080,
            "unix_seconds",
        )

        assert_window_shape(self, window)
        self.assertEqual(window["name"], "primary")
        self.assertEqual(window["used_percent"], 31.0)
        self.assertEqual(window["remaining_percent"], 69.0)
        self.assertEqual(window["reset_at"], "2026-07-13T14:28:00Z")
        self.assertEqual(window["reset_at_unix"], 1783952880)
        self.assertEqual(window["window_duration_mins"], 10080)

    def test_usage_window_clamps_remaining_percent(self) -> None:
        over_used = self.collector.usage_window("test", 150, None, None)
        under_used = self.collector.usage_window("test", -10, None, None)

        self.assertEqual(over_used["remaining_percent"], 0.0)
        self.assertEqual(under_used["remaining_percent"], 100.0)

    def test_source_error_shape(self) -> None:
        error = self.collector.source_error("example_code", "safe message")

        self.assertEqual(error, {"code": "example_code", "message": "safe message"})

    def test_claude_unauthorized_has_actionable_error(self) -> None:
        error = self.collector.claude_http_error(401, "Unauthorized")

        self.assertEqual(error["code"], "claude_auth_expired")
        self.assertNotIn("token", error["message"].lower())

    def test_collect_claude_refreshes_expired_token_and_writes_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            state_path = Path(tmp_dir) / "refresh-state.json"
            original = {
                "version": 1,
                "outerKeep": {"kept": True},
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": 999_000,
                    "scopes": ["scope-a"],
                    "subscriptionType": "team",
                    "rateLimitTier": "tier-a",
                    "nested": {"keep": "yes"},
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            calls: list[dict[str, Any]] = []

            def fake_urlopen(request, timeout=None):
                calls.append(
                    {
                        "url": request.full_url,
                        "method": request.get_method(),
                        "authorization": request.get_header("Authorization"),
                        "body": json.loads(request.data.decode("utf-8")) if request.data else None,
                    }
                )
                if request.full_url == self.collector.CLAUDE_REFRESH_ENDPOINT:
                    self.assertEqual(request.get_method(), "POST")
                    self.assertEqual(calls[-1]["body"]["grant_type"], "refresh_token")
                    self.assertEqual(calls[-1]["body"]["refresh_token"], "old-refresh")
                    self.assertEqual(calls[-1]["body"]["client_id"], self.collector.CLAUDE_REFRESH_CLIENT_ID)
                    return FakeResponse(
                        {
                            "access_token": "new-access",
                            "refresh_token": "new-refresh",
                            "expires_in": 3600,
                        }
                    )
                if request.full_url == self.collector.CLAUDE_USAGE_ENDPOINT:
                    self.assertEqual(request.get_method(), "GET")
                    self.assertEqual(request.get_header("Authorization"), "Bearer new-access")
                    return FakeResponse(
                        {
                            "five_hour": {"utilization": 12, "resets_at": "2026-07-10T10:00:00Z"},
                            "seven_day": {"utilization": 34, "resets_at": "2026-07-13T10:00:00Z"},
                            "limits": [],
                            "spend": {},
                        }
                    )
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                result = self.collector.collect_claude(str(path), 30, str(state_path))

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(result["available"])
            self.assertTrue(result["diagnostics"]["token_refreshed"])
            self.assertNotIn("refresh_writeback_failed", result["diagnostics"])
            self.assertEqual(written["outerKeep"], original["outerKeep"])
            self.assertEqual(written["claudeAiOauth"]["nested"], original["claudeAiOauth"]["nested"])
            self.assertEqual(written["claudeAiOauth"]["scopes"], original["claudeAiOauth"]["scopes"])
            self.assertEqual(written["claudeAiOauth"]["subscriptionType"], original["claudeAiOauth"]["subscriptionType"])
            self.assertEqual(written["claudeAiOauth"]["rateLimitTier"], original["claudeAiOauth"]["rateLimitTier"])
            self.assertEqual(written["claudeAiOauth"]["accessToken"], "new-access")
            self.assertEqual(written["claudeAiOauth"]["refreshToken"], "new-refresh")
            self.assertEqual(written["claudeAiOauth"]["expiresAt"], 4_600_000)
            self.assertEqual(calls[0]["url"], self.collector.CLAUDE_REFRESH_ENDPOINT)
            self.assertEqual(calls[1]["url"], self.collector.CLAUDE_USAGE_ENDPOINT)

    def test_collect_claude_refresh_failure_keeps_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            state_path = Path(tmp_dir) / "refresh-state.json"
            original = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": 999_000,
                    "scopes": ["scope-a"],
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")

            def fake_urlopen(request, timeout=None):
                if request.full_url == self.collector.CLAUDE_REFRESH_ENDPOINT:
                    raise http_error(
                        request.full_url,
                        400,
                        "Bad Request",
                        {"error": "invalid_grant", "error_description": "token rejected"},
                    )
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                result = self.collector.collect_claude(str(path), 30, str(state_path))

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(result["available"])
            self.assertEqual(result["error"]["code"], "claude_refresh_failed")
            self.assertEqual(result["diagnostics"]["refresh_status"], 400)
            self.assertEqual(result["diagnostics"]["refresh_body_keys"], ["error", "error_description"])
            self.assertEqual(written, original)

    def test_collect_claude_refresh_cooldown_skips_second_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            state_path = Path(tmp_dir) / "refresh-state.json"
            original = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": 999_000,
                    "scopes": ["scope-a"],
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            calls: list[str] = []

            def fake_urlopen(request, timeout=None):
                calls.append(request.full_url)
                raise http_error(
                    request.full_url,
                    429,
                    "Too Many Requests",
                    {"error": "rate_limited"},
                )

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                first = self.collector.collect_claude(str(path), 30, str(state_path))
                second = self.collector.collect_claude(str(path), 30, str(state_path))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(first["error"]["code"], "claude_refresh_failed")
            self.assertEqual(first["diagnostics"]["refresh_status"], 429)
            self.assertEqual(second["error"]["code"], "claude_refresh_cooldown")
            self.assertTrue(second["diagnostics"]["refresh_cooldown_active"])
            self.assertEqual(calls, [self.collector.CLAUDE_REFRESH_ENDPOINT])
            self.assertEqual(set(state.keys()), {"last_failed_attempt_ms", "last_status"})
            self.assertEqual(state["last_failed_attempt_ms"], 1_000_000)
            self.assertEqual(state["last_status"], 429)

    def test_collect_claude_refresh_state_expires_after_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            state_path = Path(tmp_dir) / "refresh-state.json"
            original = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": 999_000,
                    "scopes": ["scope-a"],
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "last_failed_attempt_ms": 399_999,
                        "last_status": 429,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            calls: list[str] = []

            def fake_urlopen(request, timeout=None):
                calls.append(request.full_url)
                if request.full_url == self.collector.CLAUDE_REFRESH_ENDPOINT:
                    raise http_error(
                        request.full_url,
                        400,
                        "Bad Request",
                        {"error": "invalid_grant"},
                    )
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                result = self.collector.collect_claude(str(path), 30, str(state_path))

            self.assertEqual(result["error"]["code"], "claude_refresh_failed")
            self.assertEqual(result["diagnostics"]["refresh_status"], 400)
            self.assertEqual(calls, [self.collector.CLAUDE_REFRESH_ENDPOINT])

    def test_collect_claude_successful_refresh_clears_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            state_path = Path(tmp_dir) / "refresh-state.json"
            original = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": 999_000,
                    "scopes": ["scope-a"],
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "last_failed_attempt_ms": 399_999,
                        "last_status": 429,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            calls: list[dict[str, Any]] = []

            def fake_urlopen(request, timeout=None):
                calls.append(
                    {
                        "url": request.full_url,
                        "method": request.get_method(),
                        "authorization": request.get_header("Authorization"),
                    }
                )
                if request.full_url == self.collector.CLAUDE_REFRESH_ENDPOINT:
                    return FakeResponse(
                        {
                            "access_token": "new-access",
                            "refresh_token": "new-refresh",
                            "expires_in": 3600,
                        }
                    )
                if request.full_url == self.collector.CLAUDE_USAGE_ENDPOINT:
                    return FakeResponse(
                        {
                            "five_hour": {"utilization": 12, "resets_at": "2026-07-10T10:00:00Z"},
                            "seven_day": {"utilization": 34, "resets_at": "2026-07-13T10:00:00Z"},
                            "limits": [],
                            "spend": {},
                        }
                    )
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                result = self.collector.collect_claude(str(path), 30, str(state_path))

            self.assertTrue(result["available"])
            self.assertTrue(result["diagnostics"]["token_refreshed"])
            self.assertFalse(state_path.exists())
            self.assertEqual([call["url"] for call in calls], [self.collector.CLAUDE_REFRESH_ENDPOINT, self.collector.CLAUDE_USAGE_ENDPOINT])

    def test_collect_claude_concurrent_change_guard_avoids_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            state_path = Path(tmp_dir) / "refresh-state.json"
            original = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "old-access",
                    "refreshToken": "old-refresh",
                    "expiresAt": 999_000,
                    "scopes": ["scope-a"],
                    "nested": {"keep": "yes"},
                },
            }
            current = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "current-access",
                    "refreshToken": "current-refresh",
                    "expiresAt": 9_999_999_999,
                    "scopes": ["scope-a"],
                    "nested": {"keep": "yes"},
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")

            def fake_urlopen(request, timeout=None):
                if request.full_url == self.collector.CLAUDE_REFRESH_ENDPOINT:
                    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
                    return FakeResponse(
                        {
                            "access_token": "new-access",
                            "refresh_token": "new-refresh",
                            "expires_in": 3600,
                        }
                    )
                if request.full_url == self.collector.CLAUDE_USAGE_ENDPOINT:
                    self.assertEqual(request.get_header("Authorization"), "Bearer current-access")
                    return FakeResponse(
                        {
                            "five_hour": {"utilization": 12, "resets_at": "2026-07-10T10:00:00Z"},
                            "seven_day": {"utilization": 34, "resets_at": "2026-07-13T10:00:00Z"},
                            "limits": [],
                            "spend": {},
                        }
                    )
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                result = self.collector.collect_claude(str(path), 30, str(state_path))

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(result["available"])
            self.assertTrue(result["diagnostics"]["token_refreshed"])
            self.assertNotIn("refresh_writeback_failed", result["diagnostics"])
            self.assertEqual(written, current)
            self.assertNotEqual(written["claudeAiOauth"]["accessToken"], "new-access")

    def test_collect_claude_valid_token_skips_refresh_and_leaves_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "credentials.json"
            original = {
                "outerKeep": "yes",
                "claudeAiOauth": {
                    "accessToken": "valid-access",
                    "refreshToken": "valid-refresh",
                    "expiresAt": 9_999_999_999,
                    "scopes": ["scope-a"],
                },
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            calls: list[str] = []

            def fake_urlopen(request, timeout=None):
                calls.append(request.full_url)
                if request.full_url == self.collector.CLAUDE_USAGE_ENDPOINT:
                    self.assertEqual(request.get_header("Authorization"), "Bearer valid-access")
                    return FakeResponse(
                        {
                            "five_hour": {"utilization": 12, "resets_at": "2026-07-10T10:00:00Z"},
                            "seven_day": {"utilization": 34, "resets_at": "2026-07-13T10:00:00Z"},
                            "limits": [],
                            "spend": {},
                        }
                    )
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with mock.patch.object(self.collector.time, "time", return_value=1_000.0), mock.patch.object(
                self.collector.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                result = self.collector.collect_claude(str(path), 30)

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(result["available"])
            self.assertNotIn("token_refreshed", result["diagnostics"])
            self.assertEqual(calls, [self.collector.CLAUDE_USAGE_ENDPOINT])
            self.assertEqual(written, original)

    def test_sample_output_shape(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(sample["schema_version"], "limit-lens.collector.v0")
        self.assertIn("captured_at", sample)
        self.assertEqual(set(sample["agents"].keys()), {"codex", "claude"})

        for agent in sample["agents"].values():
            self.assertIn("available", agent)
            self.assertIn("source", agent)
            self.assertIn("captured_at", agent)
            self.assertIn("error", agent)
            self.assertIn("diagnostics", agent)
            self.assertIn("windows", agent)
            for window in agent["windows"].values():
                assert_window_shape(self, window)

    def test_history_snapshot_sanitizes_collector_output(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        sample["agents"]["claude"]["credential_path"] = "C:/Users/user/.claude/.credentials.json"
        sample["agents"]["claude"]["diagnostics"]["oauth_keys"] = ["accessToken", "refreshToken"]
        sample["agents"]["claude"]["limits"] = [{"secret_future_field": "must not persist"}]
        sample["agents"]["claude"]["spend"] = {"raw_response": "must not persist"}
        sample["agents"]["codex"]["command"] = "C:/Users/user/AppData/Roaming/npm/codex.cmd"
        sample["agents"]["codex"]["error"] = {
            "code": "safe_code",
            "message": "C:/private/path must not persist",
        }

        snapshot = self.history.sanitize_collector_snapshot(sample)

        self.assertEqual(snapshot["schema_version"], "limit-lens.snapshot.v0")
        self.assertEqual(snapshot["collector_schema_version"], "limit-lens.collector.v0")
        self.assertNotIn("credential_path", snapshot["agents"]["claude"])
        self.assertNotIn("diagnostics", snapshot["agents"]["claude"])
        self.assertNotIn("limits", snapshot["agents"]["claude"])
        self.assertNotIn("spend", snapshot["agents"]["claude"])
        self.assertNotIn("command", snapshot["agents"]["codex"])
        self.assertEqual(snapshot["agents"]["codex"]["error"], {"code": "safe_code"})
        self.assertIn("windows", snapshot["agents"]["claude"])

    def test_history_append_writes_one_jsonl_line(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        snapshot = self.history.sanitize_collector_snapshot(sample)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "snapshots.jsonl"
            self.history.append_snapshot(output, snapshot)
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        loaded = json.loads(lines[0])
        self.assertEqual(loaded["schema_version"], "limit-lens.snapshot.v0")

    def test_history_skips_unchanged_snapshot_inside_interval(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        first = self.history.sanitize_collector_snapshot(sample)
        second = self.history.sanitize_collector_snapshot(sample)
        second["captured_at"] = "2026-07-08T14:41:00Z"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "snapshots.jsonl"
            wrote_first = self.history.append_snapshot_if_needed(output, first, now=1_000)
            os.utime(output, (1_000, 1_000))
            wrote_second = self.history.append_snapshot_if_needed(output, second, now=1_060)
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertTrue(wrote_first)
        self.assertFalse(wrote_second)
        self.assertEqual(len(lines), 1)

    def test_history_writes_visible_change_immediately(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        first = self.history.sanitize_collector_snapshot(sample)
        sample["agents"]["codex"]["windows"]["five_hour"]["used_percent"] += 1
        sample["agents"]["codex"]["windows"]["five_hour"]["remaining_percent"] -= 1
        changed = self.history.sanitize_collector_snapshot(sample)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "snapshots.jsonl"
            self.history.append_snapshot_if_needed(output, first, now=1_000)
            os.utime(output, (1_000, 1_000))
            wrote_changed = self.history.append_snapshot_if_needed(output, changed, now=1_030)
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertTrue(wrote_changed)
        self.assertEqual(len(lines), 2)

    def test_history_writes_unchanged_snapshot_after_interval(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        snapshot = self.history.sanitize_collector_snapshot(sample)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "snapshots.jsonl"
            self.history.append_snapshot_if_needed(output, snapshot, now=1_000)
            os.utime(output, (1_000, 1_000))
            wrote_again = self.history.append_snapshot_if_needed(output, snapshot, now=1_301)
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertTrue(wrote_again)
        self.assertEqual(len(lines), 2)

    def test_history_recovers_after_partial_last_line(self) -> None:
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        snapshot = self.history.sanitize_collector_snapshot(sample)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "snapshots.jsonl"
            output.write_text('{"incomplete":', encoding="utf-8")
            wrote = self.history.append_snapshot_if_needed(output, snapshot, now=1_000)
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertTrue(wrote)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[-1])["schema_version"], "limit-lens.snapshot.v0")

    def test_json_schema_file_is_parseable(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(schema["title"], "UsageTray Collector v0")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "limit-lens.collector.v0")
        self.assertIn("agent", schema["$defs"])
        self.assertIn("window", schema["$defs"])

    def test_history_sample_is_parseable(self) -> None:
        history = json.loads(HISTORY_SAMPLE_PATH.read_text(encoding="utf-8"))

        self.assertGreater(len(history), 0)
        for snapshot in history:
            self.assertEqual(snapshot["schema_version"], "limit-lens.snapshot.v0")
            self.assertIn("captured_at", snapshot)
            self.assertIn("agents", snapshot)

    def test_project_files_do_not_contain_literal_credentials(self) -> None:
        forbidden_patterns = [
            r"Bearer\\s+[A-Za-z0-9._=-]{20,}",
            r"sk-[A-Za-z0-9]{20,}",
            r"sessionKey\\s*[:=]\\s*['\"][^'\"]+",
            r"accessToken\\s*[:=]\\s*['\"][^'\"]+",
            r"refreshToken\\s*[:=]\\s*['\"][^'\"]+",
        ]
        paths = [
            COLLECTOR_PATH,
            HISTORY_PATH,
            SAMPLE_PATH,
            SCHEMA_PATH,
            APP_MAIN_PATH,
            TAURI_LIB_PATH,
            HISTORY_SAMPLE_PATH,
        ]

        for path in paths:
            source = path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                self.assertIsNone(re.search(pattern, source), f"{path}: {pattern}")


if __name__ == "__main__":
    unittest.main()
