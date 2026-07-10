# Task: Claude OAuth auto-refresh in UsageTray collector (with write-back)

Allowed write paths: D:\claude-projects\limit-lens (code, tests, PLAN.md, STATUS.md only)
Forbidden paths: C:\Users\user\.claude, C:\Users\user\.agents, D:\icloud, and anything not listed above.
CRITICAL: The real credentials file `C:\Users\user\.claude\.credentials.json` is FORBIDDEN — never read, write, or run the collector against it. All testing uses temp credential files under the project or %TEMP%.

## Goal & motivation

Claude Code's OAuth access token expires every 8 hours, so UsageTray currently shows `claude_auth_expired` almost daily and the user must re-login. The credentials file contains a `refreshToken` that nothing uses. The user approved: the collector should auto-refresh the access token when expired and write the new tokens back to the credentials file (so the `claude` CLI benefits too).

## Spec

Modify `collectors/collect_limit_lens.py` only (plus tests/docs listed below).

### 1. Refresh trigger (inside `collect_claude`, after loading `oauth` dict)

- If `oauth.get("expiresAt")` (epoch **milliseconds**) is missing, or `now_ms >= expiresAt - 300_000` (5-minute buffer), and `oauth.get("refreshToken")` is present → attempt refresh BEFORE calling the usage endpoint.
- Additionally: if the usage endpoint returns HTTP 401 with a token that looked valid, attempt ONE refresh then retry the usage call once. Never loop.

### 2. Refresh request

```
POST https://console.anthropic.com/v1/oauth/token
Content-Type: application/json
Body: {"grant_type": "refresh_token",
       "refresh_token": <refreshToken>,
       "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e"}
```

- `9d1c250a-e61b-44d9-88ed-5944d1962f5e` is Claude Code's public OAuth client_id. Use `urllib.request` like the rest of the file; timeout = the collector's `timeout_sec`.
- Expected response JSON: `access_token`, `refresh_token` (may be rotated), `expires_in` (seconds). If the response lacks `access_token`, treat as failure.
- On failure (HTTP error or bad payload): set `result["error"] = source_error("claude_refresh_failed", "<HTTP status + short reason, NO token values>")`, keep `available: false`, and return. Do NOT fall back to the expired token. Report the exact status/body shape in diagnostics as key names only, never values.

### 3. Write-back (atomic, race-aware)

Refresh tokens may be single-use/rotating, so a lost write-back can invalidate the CLI's login. Requirements:

- Re-read the credentials file immediately before writing. If its `claudeAiOauth.accessToken` no longer equals the one we started from (someone else refreshed concurrently), DISCARD our refresh result and use the file's current tokens for the usage call instead of writing.
- Otherwise update only these keys inside `claudeAiOauth`, preserving every other key at both levels untouched:
  - `accessToken` = new access_token
  - `refreshToken` = new refresh_token if present in response, else keep old
  - `expiresAt` = now_ms + expires_in * 1000 (integer)
- Atomic write: dump JSON to a temp file in the SAME directory (e.g. `.credentials.json.usagetray-tmp`), then `os.replace()` onto the target. Encoding utf-8. Preserve the original file's top-level structure exactly (json.dumps with the same general formatting is fine; do not drop keys).
- If write-back fails after a successful refresh: still use the new token for this run's usage call, but add `result["diagnostics"]["refresh_writeback_failed"] = True` and put a `claude_refresh_writeback_failed` warning into diagnostics (collection itself should still succeed).
- Add `result["diagnostics"]["token_refreshed"] = True` when a refresh happened. Never print or store token values anywhere (stdout, diagnostics, exceptions). Extend the existing redaction pattern (see lines ~410-414) to also redact the refresh token and new access token in exception messages.

### 4. Error hint

In `collectors/telegram_bridge.py`, add to `ERROR_HINTS`:
`"claude_refresh_failed": "Claude token 自動更新失敗，請重新登入 Claude Code。"`

### 5. Tests

Extend `collectors/test_collect_limit_lens_contract.py` following its existing style (plain functions run by the script, no pytest dependency assumed — check how it currently runs). Add unit tests using temp credential files + monkeypatched `urllib.request.urlopen`:

1. Expired token + successful refresh → usage call uses new token, file rewritten with new accessToken/refreshToken/expiresAt, other keys preserved byte-for-byte in value.
2. Expired token + refresh HTTP 400 → `error.code == "claude_refresh_failed"`, file NOT modified.
3. Concurrent-change guard: file's accessToken changes between initial read and write-back → file NOT overwritten with our result.
4. Valid (non-expired) token → no refresh request made, file untouched.

### 6. Docs

- `PLAN.md`: find the lines saying v1 does not auto-refresh and must not write back to `.credentials.json` (search for "refresh" and "寫回"). Update them to state this decision was superseded on 2026-07-10 by user request: collector now auto-refreshes and atomically writes back; keep a one-line note of the old policy for history. Match the file's existing Traditional Chinese style.
- `STATUS.md`: append entry `### 27. Claude OAuth auto-refresh (2026-07-10)` in the same style as entries 19–26: what changed, files touched, how tested. Traditional Chinese.

## Rules

- One step at a time; if any command errors, stop and report the command + raw error verbatim. Do not guess-fix.
- Do not run the collector against the real credentials file. Do not print token values ever.
- Keep the existing code style (stdlib only, type hints, `source_error` helper, diagnostics keys as booleans/counts not values).

## Verify (do these yourself before reporting)

- `python collectors/test_collect_limit_lens_contract.py` → all tests pass (old 15 + new ones); paste the output summary.
- `python -c "import ast; ast.parse(open('collectors/collect_limit_lens.py', encoding='utf-8').read())"` passes.
- `git status` / `git diff --stat` shows only the intended files changed.

## Report format

- Conclusion first, ≤30 lines. Each "done" claim needs evidence (command output or file:line). State clearly anything uncertain or skipped.
