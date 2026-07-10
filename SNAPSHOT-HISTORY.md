# Limit Lens Snapshot History

Updated: 2026-07-08 22:40:00 +08:00

This document defines how Limit Lens should save usage history safely.

Plain-language meaning: the collector reads the meters. Snapshot history is the notebook that records only safe meter readings over time.

## Decision

Start v1 history with JSONL snapshots, not SQLite.

Reason:

- JSONL is simple to inspect while the collector shape is still young.
- Each line can be one complete safe snapshot.
- It is easier to debug before the tray app exists.
- SQLite can come later when charts, filtering, and retention become more serious.

Recommended path once the app shell exists:

```text
%APPDATA%\LimitLens\snapshots.jsonl
```

Development note:

- The collector should still print to stdout.
- A separate app/history layer should decide whether to save the snapshot.
- The collector should not become the owner of long-term storage.

## What one snapshot means

One snapshot is one safe reading of Codex and Claude usage at one moment.

It should answer:

- Was Codex available?
- Was Claude available?
- How much of each known limit was used?
- How much remained?
- When will each window reset?
- Which safe source produced the value?
- If unavailable, what safe error code happened?

It should not answer:

- What the user typed.
- What files were edited.
- What prompts or completions said.
- What token, cookie, or session key was used.
- What raw API response was returned.

## JSONL format

JSONL means one JSON object per line.

Example:

```jsonl
{"schema_version":"limit-lens.snapshot.v0","captured_at":"2026-07-08T14:40:00Z","agents":{"codex":{"available":true,"source":"codex_app_server","windows":{"five_hour":{"used_percent":5.0,"remaining_percent":95.0,"reset_at":"2026-07-08T19:08:41Z"},"weekly":{"used_percent":31.0,"remaining_percent":69.0,"reset_at":"2026-07-13T14:28:00Z"}}},"claude":{"available":true,"source":"claude_code_oauth","windows":{"five_hour":{"used_percent":13.0,"remaining_percent":87.0,"reset_at":"2026-07-08T14:30:00Z"},"weekly":{"used_percent":90.0,"remaining_percent":10.0,"reset_at":"2026-07-11T03:00:00Z"},"weekly_scoped":{"used_percent":99.0,"remaining_percent":1.0,"reset_at":"2026-07-11T03:00:00Z"}}}}}
```

The actual file should be compact JSON, one line per snapshot.

## Snapshot schema

Snapshot schema version:

```json
"schema_version": "limit-lens.snapshot.v0"
```

Required top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Snapshot history contract version. |
| `captured_at` | UTC ISO 8601 time when the snapshot was saved. |
| `agents` | Sanitized per-agent data. |

Agent fields to store:

| Field | Store? | Reason |
| --- | --- | --- |
| `available` | yes | Needed for charts and unavailable states. |
| `source` | yes | Needed to explain where data came from. |
| `captured_at` | optional | Useful if source collection times differ. |
| `error.code` | yes | Safe and useful for reliability history. |
| `error.message` | optional | Store only if sanitized; UI can often avoid it. |
| `windows` | yes | Core history data. |
| `limits` | optional | Store only sanitized Claude limit metadata. |
| `spend` | optional | Store only sanitized spend summary if present. |
| `diagnostics` | no by default | Useful for debugging, but not needed for history. |
| `command` | no | Not useful for charts. |
| `credential_path` | no | Avoid storing local account paths in history. |

Window fields to store:

| Field | Store? | Reason |
| --- | --- | --- |
| `used_percent` | yes | Main chart value. |
| `remaining_percent` | yes | Useful for status copy and warnings. |
| `reset_at` | yes | Needed for countdown and reset grouping. |
| `window_duration_mins` | yes | Needed to distinguish 5-hour and weekly windows. |
| `name` | optional | Useful for debugging source mapping. |
| `reset_at_unix` | optional | Redundant if `reset_at` exists. |

## Fields that must never be stored

Do not store:

- access tokens;
- refresh tokens;
- Authorization headers;
- browser cookies;
- browser session keys;
- raw credentials files;
- raw API response bodies;
- prompt text;
- completion text;
- transcript contents;
- edited file contents;
- MCP authorization headers.

## Write timing

Recommended v1 write rhythm:

- Poll every 60 seconds while the tray app is running.
- Save a snapshot every 5 minutes even if nothing changed.
- Save immediately when any visible percentage changes by at least 1 percentage point.
- Save immediately when a reset time changes.
- Save immediately when a source changes between available and unavailable.

Why not every few seconds:

- The limits do not need second-by-second history.
- Smaller files are easier to inspect.
- Less writing means fewer weird app bugs.

## Retention

Recommended v1 retention:

- Keep raw JSONL snapshots for 90 days.
- Later, compact older data into daily summaries.
- Do not build retention before the first tray prototype unless the file grows too fast.

## Unavailable source behavior

When Codex or Claude is unavailable:

- Store `available: false`.
- Store safe `error.code`.
- Do not invent usage percentages.
- Do not carry forward old usage as if it were current.
- UI may show the last known good snapshot separately, clearly labeled as stale.

## Chart ideas enabled by history

History can later support:

- usage over time;
- how close the user gets to 100%;
- how often each source becomes unavailable;
- how long high-usage periods last;
- whether 5-hour or weekly quota is the real bottleneck;
- reset-time markers on charts.

## Implementation order

1. Keep collector stdout-only.
2. Add a small history writer that accepts collector JSON.
3. Write compact JSONL lines to `%APPDATA%\LimitLens\snapshots.jsonl`.
4. Add a reader that returns recent snapshots for UI charts.
5. Move to SQLite only when chart queries become painful.

## Current answer for v1

Use JSONL first.

Do not store diagnostics by default.

Do not store credential paths.

Do not build UI until the sample output and schema are stable enough for the frontend to consume.

## Implementation status

Implemented on 2026-07-09:

- `collectors/history_snapshot.py` owns sanitization and JSONL write policy.
- The Tauri app passes only completed collector JSON to the history writer.
- Native history path is `%APPDATA%\LimitLens\snapshots.jsonl`.
- Unknown agent fields are dropped.
- Error messages are dropped; only safe error codes are retained.
- Diagnostics, local paths, limits, and spend objects are dropped.
- Visible changes are written immediately.
- Unchanged readings are written every 5 minutes.
- Partial final lines are isolated so later valid readings can still be appended.
- The Tauri reader returns a bounded number of recent snapshots.
- The frontend includes a compact 24-hour peak view.
