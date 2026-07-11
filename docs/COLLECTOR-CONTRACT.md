# UsageTray Collector Contract

Updated: 2026-07-08 22:25:00 +08:00

This document defines the first stable data contract for the UsageTray collector.

Plain-language meaning: this is the receipt format. The collector reads Codex and Claude usage, then prints one sanitized JSON receipt. The future tray UI should read this receipt instead of guessing provider-specific fields.

## Contract version

Current collector schema:

```json
"schema_version": "usage-tray.collector.v0"
```

Rules:

- `schema_version` is required.
- A UI may refuse to parse unknown schema versions.
- Breaking field changes must use a new schema version.
- Adding optional fields is allowed inside the same schema version.

## Top-level shape

Required top-level fields:

```json
{
  "schema_version": "usage-tray.collector.v0",
  "captured_at": "2026-07-08T14:25:00Z",
  "agents": {
    "codex": {},
    "claude": {}
  }
}
```

Field meaning:

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Contract name and version. |
| `captured_at` | yes | When the combined snapshot was produced, in UTC ISO 8601. |
| `agents` | yes | Per-agent result objects. |
| `agents.codex` | only when Codex is not skipped | Codex quota result. |
| `agents.claude` | only when Claude is not skipped | Claude quota result. |

Time rule:

- Machine-readable timestamps use UTC ISO 8601, ending in `Z`.
- UI may display reset times in local time, such as Taiwan time.
- Collector should not mix display strings into machine fields.

## Agent result shape

Each agent result should follow this common shape:

```json
{
  "available": true,
  "source": "codex_app_server",
  "captured_at": "2026-07-08T14:25:00Z",
  "error": null,
  "diagnostics": {},
  "windows": {}
}
```

Common fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `available` | yes | `true` means this source produced usable quota data. |
| `source` | yes | Internal source label, safe to show in an advanced/debug view. |
| `captured_at` | yes | When this individual source was collected, in UTC ISO 8601. |
| `error` | yes | `null` if successful, otherwise a safe error object. |
| `diagnostics` | yes | Sanitized debug information. Never contains credentials. |
| `windows` | yes | Usage windows, such as 5-hour or weekly limits. |

Important UI rule:

- Use `available` first.
- If `available` is `false`, show an unavailable state instead of pretending usage is 0%.
- If a specific window is missing, show that window as unavailable.

## Window shape

A usage window looks like this:

```json
{
  "name": "primary",
  "used_percent": 31.0,
  "remaining_percent": 69.0,
  "reset_at": "2026-07-13T14:28:00Z",
  "reset_at_unix": 1783952880,
  "window_duration_mins": 10080
}
```

Window fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Source-native window name. |
| `used_percent` | yes, nullable | How much quota has been used, from 0 to 100 when known. |
| `remaining_percent` | yes, nullable | `100 - used_percent`, clamped between 0 and 100. |
| `reset_at` | yes, nullable | Reset time in UTC ISO 8601 when known. |
| `reset_at_unix` | yes, nullable | Reset time as Unix seconds when the source gave Unix seconds. |
| `window_duration_mins` | yes, nullable | Window length in minutes when known. |

Percent rule:

- `used_percent` means already used.
- `remaining_percent` means still available.
- Codex UI often displays remaining percent, while Codex app-server gives used percent.
- Claude UI displays used percent.
- The tray UI should label clearly, not assume every provider UI uses the same wording.

Bar chart rule:

- Use `used_percent` for the filled part if the label says usage.
- Use `remaining_percent` for the filled part if the label says remaining.
- For UsageTray v1, prefer showing usage bars with clear reset times.

## Codex result

Expected Codex result:

```json
{
  "available": true,
  "source": "codex_app_server",
  "windows": {
    "five_hour": {},
    "weekly": {}
  }
}
```

Codex window mapping:

| UsageTray window | Codex app-server field | Meaning |
| --- | --- | --- |
| `five_hour` | `rateLimits.primary` | 5-hour limit. |
| `weekly` | `rateLimits.secondary` | Weekly limit. |

Codex expected fields:

- `usedPercent`
- `windowDurationMins`
- `resetsAt`

Codex reset conversion:

- Source `resetsAt` is Unix seconds.
- Collector stores the converted value in `reset_at`.
- Collector also keeps the original seconds in `reset_at_unix`.

## Claude result

Expected Claude result:

```json
{
  "available": true,
  "source": "claude_code_oauth",
  "windows": {
    "five_hour": {},
    "weekly": {},
    "weekly_scoped": {}
  },
  "limits": [],
  "spend": null
}
```

Claude window mapping:

| UsageTray window | Claude OAuth usage field | Meaning |
| --- | --- | --- |
| `five_hour` | `five_hour` | 5-hour limit. |
| `weekly` | `seven_day` | Weekly all-models limit. |
| `weekly_scoped` | `limits.kind == weekly_scoped` | Model-scoped weekly limit, such as Fable. |

Claude reset conversion:

- Source `resets_at` is already an ISO-like timestamp.
- Collector stores it in `reset_at`.
- `reset_at_unix` is `null` for Claude OAuth windows in v0.

Claude `limits` safety rule:

- The collector may preserve safe limit metadata such as `kind`, `group`, `percent`, `severity`, `resets_at`, and `is_active`.
- The collector must not preserve raw model identifiers if they could become account-specific or unnecessarily detailed.
- v0 only records booleans like `model_display_name_present` and `surface_present` inside sanitized `scope`.

## Error shape

When a source is unavailable, the result should look like this:

```json
{
  "available": false,
  "source": "claude_code_oauth",
  "error": {
    "code": "claude_credentials_not_found",
    "message": "Claude credentials not found: C:\\Users\\user\\.claude\\.credentials.json"
  },
  "windows": {}
}
```

Error fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `code` | yes | Stable machine-readable error code. |
| `message` | yes | Human-readable safe message. |

Safe error rule:

- Error messages must never include access tokens, refresh tokens, cookies, session keys, Authorization headers, or raw API responses.
- File paths may be shown if they only identify expected local config locations.
- HTTP status code and reason may be shown.

## Diagnostics rule

Diagnostics are allowed only when sanitized.

Allowed examples:

- Response top-level keys.
- Whether a credential field exists.
- Count of scopes.
- Source version or user-agent string.
- Plan type or limit name when returned by the source.

Forbidden examples:

- Access token values.
- Refresh token values.
- Browser session keys.
- Cookies.
- Authorization headers.
- Raw prompt text.
- Conversation transcript text.
- Raw API response bodies.

## Storage rule

The collector itself prints JSON to stdout and should not persist data.

When the app later adds history storage, it may store:

- `schema_version`
- `captured_at`
- `available`
- `source`
- safe `error.code`
- usage windows
- sanitized `limits`
- sanitized `spend`

It must not store:

- Tokens.
- Cookies.
- Session keys.
- Raw credentials files.
- Raw API responses.
- Prompts.
- Message history.
- Edited file content.

## v0 UI dependency list

The first tray UI may depend on these fields:

- `schema_version`
- `captured_at`
- `agents.codex.available`
- `agents.codex.windows.five_hour.used_percent`
- `agents.codex.windows.five_hour.remaining_percent`
- `agents.codex.windows.five_hour.reset_at`
- `agents.codex.windows.weekly.used_percent`
- `agents.codex.windows.weekly.remaining_percent`
- `agents.codex.windows.weekly.reset_at`
- `agents.claude.available`
- `agents.claude.windows.five_hour.used_percent`
- `agents.claude.windows.five_hour.remaining_percent`
- `agents.claude.windows.five_hour.reset_at`
- `agents.claude.windows.weekly.used_percent`
- `agents.claude.windows.weekly.remaining_percent`
- `agents.claude.windows.weekly.reset_at`
- `agents.claude.windows.weekly_scoped.used_percent`
- `agents.claude.windows.weekly_scoped.remaining_percent`
- `agents.claude.windows.weekly_scoped.reset_at`

Everything else should be treated as optional v0 debug/supporting data.

## Known v0 limits

- Claude OAuth usage endpoint is useful but not public-stability guaranteed.
- Claude OAuth refresh is optional and enabled by the tray app by default. When enabled, an expired token may be refreshed and atomically written back to the existing Claude credentials file after creating one adjacent `.bak` backup. The collector supports a read-only `--no-claude-refresh` mode.
- Collector does not read Claude browser session keys.
- Collector does not install Claude statusLine hooks.
- History is written by the separate history helper, not by collector stdout handling.

## Next contract tasks

- Add a JSON Schema file after the v0 Python shape settles.
- Add a sample sanitized output file for UI development.
- Add snapshot-history contract before writing any local database.
