# SPIKE: Codex app-server `account/rateLimits/read`

Date: 2026-07-08 21:35 Taiwan time
Project: Limit Lens
Scope: read-only datasource validation only

## Goal

Validate whether Limit Lens can use local Codex app-server as the primary Codex quota datasource:

- spawn `codex app-server` over stdio;
- perform JSON-RPC initialize handshake;
- call `account/rateLimits/read`;
- confirm whether `usedPercent`, `windowDurationMins`, and `resetsAt` are available.

## Safety Controls Used

- No Codex prompt, model call, or token-consuming request was made.
- No Codex session JSONL or conversation content was read.
- No token, refresh token, id token, account id, or authorization header was printed.
- `~\.codex\auth.json` was inspected only for non-sensitive shape and expiry metadata.

## Local CLI Discovery

| Check | Result |
| --- | --- |
| `codex.ps1` from PowerShell | blocked by local execution policy. |
| `C:\Users\user\AppData\Roaming\npm\codex.cmd --version` | `codex-cli 0.142.5`. |
| WindowsApps `codex.exe` direct subprocess spawn | blocked by Windows permission error `WinError 5`. |
| Usable command for tray collector | `C:\Users\user\AppData\Roaming\npm\codex.cmd`. |

## JSON-RPC Probe

Commands tested:

- `codex.cmd app-server`
- `codex.cmd app-server --disable plugins`

Handshake request:

- method: `initialize`
- client name: `limit-lens-spike`

Handshake result: success for both commands.

Initialize result keys:

- `codexHome`
- `platformFamily`
- `platformOs`
- `userAgent`

Then the probe sent:

- method: `initialized`
- method: `account/rateLimits/read`

## `account/rateLimits/read` Result

Both command variants returned the same JSON-RPC error:

```json
{
  "code": -32600,
  "message": "codex account authentication required to read rate limits"
}
```

No `result.rateLimits` payload was returned in this environment, so these fields were not available:

| Field | Confirmed? | Notes |
| --- | --- | --- |
| `rateLimits.primary.usedPercent` | no | Blocked by Codex account authentication state. |
| `rateLimits.primary.windowDurationMins` | no | Blocked by Codex account authentication state. |
| `rateLimits.primary.resetsAt` | no | Blocked by Codex account authentication state. |
| `rateLimits.secondary.usedPercent` | no | Blocked by Codex account authentication state. |
| `rateLimits.secondary.windowDurationMins` | no | Blocked by Codex account authentication state. |
| `rateLimits.secondary.resetsAt` | no | Blocked by Codex account authentication state. |

## Sanitized Auth State Check

`C:\Users\user\.codex\auth.json` exists. Sanitized shape:

| Field | Result |
| --- | --- |
| `auth_mode` | `chatgpt` |
| `OPENAI_API_KEY` present | false |
| `tokens` object present | true |
| access token present | true |
| refresh token present | true |
| id token present | true |
| account id present | true |
| access token expiry | `2026-07-16T11:28:31Z` |
| id token expiry | `2026-07-06T12:28:31Z` |
| `codex login status` | `Not logged in` |

Interpretation: app-server is reachable and the RPC method exists, but Codex currently considers the CLI not logged in. The expired id token plus `codex login status` likely explains the authentication error.

## Conclusion

The Codex app-server datasource path is structurally viable on Windows:

- `codex.cmd` can be spawned by a tray app;
- the JSON-RPC initialize handshake works;
- `account/rateLimits/read` is recognized by the server.

The current machine state does not confirm the quota field payload because Codex account authentication is invalid from the CLI's point of view. Limit Lens should treat this as a recoverable source error, not as absence of the API.

## Next Step

After refreshing Codex login state with the official CLI/app flow, re-run the same probe. Expected successful payload shape, based on QuotaGem's verified parser, is:

- `result.rateLimits.primary.usedPercent`
- `result.rateLimits.primary.windowDurationMins`
- `result.rateLimits.primary.resetsAt`
- `result.rateLimits.secondary.usedPercent`
- `result.rateLimits.secondary.windowDurationMins`
- `result.rateLimits.secondary.resetsAt`

For v1 implementation, show `Codex account authentication required` when this JSON-RPC error appears, and do not silently fall back to stale local logs for quota percentages.

## Follow-up: After Codex Login Refresh

Date: 2026-07-08 21:44 Taiwan time

After the user refreshed Codex login state in a normal PowerShell session, the same read-only app-server probe was re-run outside the restricted sandbox.

Result: success.

Initialize result:

- `codexHome`: `C:\Users\user\.codex`
- `platformFamily`: `windows`
- `platformOs`: `windows`
- `userAgent`: `Codex Desktop/0.142.5 ... (limit-lens-spike; 0.0.0)`

`account/rateLimits/read` returned:

| Window | `usedPercent` | `windowDurationMins` | `resetsAt` |
| --- | ---: | ---: | ---: |
| `primary` | 31 | 300 | 1783519522 |
| `secondary` | 28 | 10080 | 1783952880 |

Additional top-level keys observed:

- `rateLimits`
- `rateLimitsByLimitId`
- `rateLimitResetCredits`

Additional `rateLimits` keys observed:

- `credits`
- `individualLimit`
- `limitId`
- `limitName`
- `planType`
- `primary`
- `rateLimitReachedType`
- `secondary`

Updated conclusion: Codex app-server is confirmed as a viable v1 primary datasource on this Windows machine. The earlier failure was caused by the environment/auth state seen by the sandboxed probe, not by absence of the app-server API.
