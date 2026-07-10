# Limit Lens collectors

This folder holds the first minimal data collector and history-snapshot prototype for Limit Lens.

## `collect_limit_lens.py`

Reads the two confirmed primary data sources and writes one sanitized JSON object to stdout:

- Codex: spawns `codex.cmd app-server --disable plugins`, then calls `account/rateLimits/read`.
- Claude: reads `~/.claude/.credentials.json`, uses `claudeAiOauth.accessToken` in memory, and calls `https://api.anthropic.com/api/oauth/usage`.

Safety rules:

- does not print access tokens, refresh tokens, cookies, or session keys;
- does not write to `~/.claude`, `~/.codex`, config, logs, or a database;
- does not refresh Claude OAuth tokens;
- does not read conversation transcripts;
- returns source errors as JSON instead of throwing raw output.

Run from PowerShell:

```powershell
python .\collectors\collect_limit_lens.py
```

## `history_snapshot.py`

Converts collector JSON into a safe JSONL history snapshot.

It keeps:

- availability;
- source labels;
- safe error codes;
- usage windows;

It drops by default:

- diagnostics;
- error messages;
- limits and spend objects until their history schema is explicitly defined;
- command paths;
- credential paths;
- anything not needed for future history charts.

Write policy:

- write immediately when a visible percentage, reset time, availability, source, or error code changes;
- otherwise write one unchanged reading every 5 minutes;
- keep the collector stdout-only and let the app choose the output path.

Example:

```powershell
python .\collectors\history_snapshot.py --input .\samples\collector-output-v0.sample.json --output .\snapshots.dev.jsonl
```

## Tests

Run the local contract checks without live Codex/Claude calls:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python .\collectors\test_collect_limit_lens_contract.py
```

Current checks cover:

- collector schema version;
- usage window shape;
- remaining percentage calculation;
- sample output shape;
- JSON Schema parseability;
- history snapshot sanitization;
- JSONL append behavior;
- 5-minute unchanged-reading deduplication;
- immediate visible-change writes;
- interrupted-line recovery;
- browser history sample shape;
- obvious literal credential patterns.

## Contract files

- `COLLECTOR-CONTRACT.md`: stable v0 JSON meaning.
- `SNAPSHOT-HISTORY.md`: safe history storage plan.
- `samples/collector-output-v0.sample.json`: sanitized UI development sample.
- `schemas/collector-v0.schema.json`: first JSON Schema draft.

Expected top-level collector shape:

```json
{
  "schema_version": "limit-lens.collector.v0",
  "captured_at": "2026-07-08T00:00:00.0000000Z",
  "agents": {
    "codex": {
      "available": true,
      "source": "codex_app_server",
      "windows": {
        "five_hour": {},
        "weekly": {}
      }
    },
    "claude": {
      "available": true,
      "source": "claude_code_oauth",
      "windows": {
        "five_hour": {},
        "weekly": {},
        "weekly_scoped": {}
      },
      "limits": []
    }
  }
}
```
