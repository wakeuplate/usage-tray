# Task: Refresh-attempt cooldown for Claude OAuth refresh in UsageTray collector

Allowed write paths: D:\claude-projects\limit-lens (collectors/collect_limit_lens.py, collectors/test_collect_limit_lens_contract.py only)
Forbidden paths: C:\Users\user\.claude, C:\Users\user\.agents, D:\icloud, and anything not listed above.
CRITICAL: Never read/write the real `C:\Users\user\.claude\.credentials.json` or run the collector against it. Tests use temp files only.

## Goal & motivation

The collector (collectors/collect_limit_lens.py) now auto-refreshes the Claude OAuth token (function `refresh_claude_credentials`, called from `collect_claude`). The tray app runs the collector every 2 minutes. Live testing showed Anthropic's token endpoint (`https://console.anthropic.com/v1/oauth/token`) rate-limits aggressively (HTTP 429 after a few attempts). Without a cooldown, a broken/expired refresh token means the app hammers the endpoint every 2 minutes forever. Add a persistent cooldown so a FAILED refresh attempt is not retried for 10 minutes.

## Spec

1. New module-level constants in collect_limit_lens.py:
   - `REFRESH_COOLDOWN_MS = 600_000`
   - State file path helper: `%APPDATA%\UsageTray\claude-refresh-state.json` (use `os.environ.get("APPDATA")`; if APPDATA unset, cooldown is silently disabled). Add a `--refresh-state-file` CLI argument overriding the default path (needed for tests).
2. State file content: `{"last_failed_attempt_ms": <int>, "last_status": <int or str>}`. Only FAILED attempts write it; a successful refresh DELETES the state file (or writes last_failed_attempt_ms = null).
3. Behavior in `collect_claude`, wherever a refresh would be attempted (both the expiry-triggered path and the 401-retry path):
   - Before attempting: if state file exists, parses, and `now_ms - last_failed_attempt_ms < REFRESH_COOLDOWN_MS` → skip the refresh attempt entirely. Set `result["error"] = source_error("claude_refresh_cooldown", "Refresh recently failed; retrying after cooldown.")`, add `result["diagnostics"]["refresh_cooldown_active"] = True`, keep available False, return (for the expiry path). For the 401 path: skip the refresh+retry and fall through to the normal 401 error (`claude_auth_expired`), also with the `refresh_cooldown_active` diagnostic.
   - After a failed refresh (`claude_refresh_failed`): write the state file. Failure to write the state file must NOT break collection (wrap in try/except, add `diagnostics["cooldown_write_failed"] = True`).
   - After a successful refresh: clear the state file (ignore errors).
   - Corrupt/unparseable state file → treat as no cooldown, overwrite on next failure.
4. No token values ever go into the state file or output.
5. In collectors/telegram_bridge.py `ERROR_HINTS`, add: `"claude_refresh_cooldown": "Claude 權杖刷新剛失敗，冷卻中稍後自動重試。"`

## Tests

Extend collectors/test_collect_limit_lens_contract.py in existing style, using temp dirs for both credentials and the refresh-state file:
1. Failed refresh writes the state file; immediate second collect run skips refresh (no HTTP call to token endpoint — assert via mock call counter) and returns `claude_refresh_cooldown`.
2. State file older than 10 min → refresh IS attempted again.
3. Successful refresh clears the state file.

## Rules
- One step at a time; on any command error stop and report the command + raw error verbatim.
- Keep existing style (stdlib only, type hints, source_error helper).
- NOTE: the file was recently edited; read the current version first, do not assume line numbers.

## Verify
- `python collectors/test_collect_limit_lens_contract.py` → all pass (19 existing + 3 new); paste summary.
- `python -c "import ast; ast.parse(open('collectors/collect_limit_lens.py', encoding='utf-8').read())"` passes.

## Report format
- Conclusion first, ≤30 lines; every claim with evidence (command output or file:line); state uncertainties explicitly.
