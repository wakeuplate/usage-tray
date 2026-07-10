# SPIKE: Claude OAuth `.credentials.json`

Date: 2026-07-08 21:35 Taiwan time
Project: Limit Lens
Scope: read-only datasource validation only

## Goal

Validate whether the local Claude Code OAuth credential source can support Limit Lens v1:

- find `%USERPROFILE%\.claude\.credentials.json` or WSL `.credentials.json`;
- do not print, copy, persist, refresh, or log tokens;
- call `https://api.anthropic.com/api/oauth/usage` only if a suitable Claude Code account OAuth access token is found;
- summarize only sanitized fields useful for 5h / weekly quota UI.

## Safety Controls Used

- The credential file was read only.
- No file under `C:\Users\user\.claude\` was modified.
- No token, refresh token, sessionKey, cookie, authorization header, or raw credential JSON was printed.
- Nested token-like fields were treated as sensitive and were not used unless they matched the expected Claude Code account OAuth shape.
- No token refresh was attempted.

## Candidate Search

| Source | Result | Notes |
| --- | --- | --- |
| `C:\Users\user\.claude\.credentials.json` | exists | Last modified `2026-07-08T08:38:40.7884455Z`, length `2265` bytes. |
| `\\wsl.localhost` | unavailable | Root path did not exist in this Windows session. |
| `\\wsl$` | unavailable | Root path did not exist in this Windows session. |

Selected candidate: `C:\Users\user\.claude\.credentials.json`.

## Sanitized Credential Shape

Top-level keys found:

- `mcpOAuth`

Expected Claude Code account OAuth shapes were not found:

- no top-level `claudeAiOauth` / `claude_ai_oauth` object;
- no recognized top-level account `accessToken` / `access_token` field;
- no recognized account `refreshToken` / `refresh_token` field;
- no recognized account `expiresAt` / `expires_at` field.

The file does contain nested `accessToken` fields under `mcpOAuth.plugin:data:*` entries. Those appear to be MCP/plugin OAuth credentials, not the Claude Code account OAuth credential needed for `api.anthropic.com/api/oauth/usage`. They were deliberately ignored.

## Usage Endpoint Result

Endpoint: `https://api.anthropic.com/api/oauth/usage`

Status: not safely attempted.

Reason: no suitable Claude Code account OAuth bearer token was found in the expected credential locations. Calling the Anthropic usage endpoint with unrelated MCP/plugin OAuth tokens would be both invalid and outside the intended safety boundary.

## Fields Confirmed

Because the usage endpoint was not called with a valid Claude Code account OAuth token, no quota fields were confirmed in this environment.

| Field | Confirmed? | Notes |
| --- | --- | --- |
| 5h percent / utilization | no | Blocked by missing suitable OAuth token. |
| 5h reset time | no | Blocked by missing suitable OAuth token. |
| weekly percent / utilization | no | Blocked by missing suitable OAuth token. |
| weekly reset time | no | Blocked by missing suitable OAuth token. |

## Conclusion

The `.credentials.json` file exists, but this machine's current file shape is not the `sr-kai/claudeusagewin` style Claude Code account OAuth credential described in `RESEARCH-datasource-20260707.md`. It currently looks like an MCP OAuth credential store.

For Limit Lens v1, keep Claude OAuth as the preferred safe datasource, but implement the collector defensively:

- search for expected account OAuth shapes first;
- explicitly reject `mcpOAuth.plugin:data:*` tokens;
- show `Claude OAuth unavailable` when only MCP OAuth credentials are present;
- do not fall back to browser `sessionKey` unless the user opts into Precision Mode later.

## Next Step

Re-run this spike after confirming where the installed Claude Code version stores its account OAuth credential on Windows, or after Claude Code has been re-authenticated in a way that creates the expected account OAuth entry.

## Follow-up: After Claude Code `auth login`

Date: 2026-07-08 21:52 Taiwan time

After the user signed in with `claude auth login`, `C:\Users\user\.claude\.credentials.json` was updated and now contains the expected Claude Code account OAuth object.

Sanitized credential shape:

- top-level keys: `claudeAiOauth`, `mcpOAuth`
- `claudeAiOauth` keys: `accessToken`, `expiresAt`, `rateLimitTier`, `refreshToken`, `scopes`, `subscriptionType`
- access token present: yes
- refresh token present: yes
- scopes count: 5
- no token or refresh token value was printed or persisted
- no token refresh was attempted

Usage endpoint:

- endpoint: `https://api.anthropic.com/api/oauth/usage`
- result: success
- required headers used: `Authorization: Bearer <redacted>`, `User-Agent: claude-code/2.1.199`, `anthropic-beta: oauth-2025-04-20`

Top-level keys observed:

- `five_hour`
- `seven_day`
- `limits`
- `spend`
- `extra_usage`
- `member_dashboard_available`
- additional nullable / experiment-like keys: `seven_day_oauth_apps`, `seven_day_opus`, `seven_day_sonnet`, `seven_day_cowork`, `seven_day_omelette`, `tangelo`, `iguana_necktie`, `omelette_promotional`, `nimbus_quill`, `cinder_cove`, `amber_ladder`

Confirmed quota fields:

| Field | Value |
| --- | ---: |
| `five_hour.utilization` | 13.0 |
| `five_hour.resets_at` | `2026-07-08T14:29:59.734754+00:00` |
| `seven_day.utilization` | 90.0 |
| `seven_day.resets_at` | `2026-07-11T02:59:59.734785+00:00` |

Taiwan-time reset interpretation:

| Window | Reset time |
| --- | --- |
| 5h / session | 2026-07-08 22:29:59 UTC+8 |
| weekly | 2026-07-11 10:59:59 UTC+8 |

`limits[]` also provides normalized rows:

| `kind` | `group` | `percent` | `severity` | `is_active` |
| --- | --- | ---: | --- | --- |
| `session` | `session` | 13 | `normal` | false |
| `weekly_all` | `weekly` | 90 | `critical` | false |
| `weekly_scoped` | `weekly` | 99 | `critical` | true |

Updated conclusion: Claude Code OAuth `.credentials.json` is confirmed as a viable v1 primary Claude datasource after `claude auth login`. The collector should read only `claudeAiOauth.accessToken`, call the usage endpoint on demand, discard the token immediately after the request, and persist only sanitized usage fields such as utilization, reset time, limit kind/group, severity, and freshness.
