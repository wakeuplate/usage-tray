# UsageTray

[繁體中文](README.md)

A Windows system tray utility that puts **Codex** and **Claude Code** usage in one panel: quota and reset times at a glance, proactive Telegram alerts when you're about to run out, and automatic renewal of expired Claude tokens.

Core idea: **use whichever agent still has quota** — if you subscribe to more than one AI coding agent, you shouldn't have to track limits in your head.

| Now | Trends | Alerts |
|---|---|---|
| ![Now](docs/screenshots/now.png) | ![Trends](docs/screenshots/24h.png) | ![Alerts](docs/screenshots/alerts.png) |

## What's different here

Most usage-display tools only cover one provider and only display. UsageTray:

- **Both providers, one panel**: Codex (5-hour + weekly) and Claude Code (5-hour + weekly + per-model scoped) side by side, so choosing which agent to use is a glance, not a lookup.
- **Reaches out instead of waiting to be checked**: Telegram alerts fire when usage crosses 50%/85%/95% (with a text usage bar chart); send `/usage` to the bot anytime to pull the current numbers, even away from the desktop.
- **Refreshes Claude's token, and the CLI benefits too**: Claude Code's OAuth token expires every 8 hours. UsageTray refreshes it automatically and atomically writes the new token back to the credentials file (with a concurrency guard and a failure cooldown), so the `claude` CLI itself stops prompting you to sign in again.
- **Light**: Tauri-packaged, 2.5 MB installer, single-digit MB idle memory.
- **History is kept and analyzable**: every reading is appended to a local JSONL file (`%APPDATA%\UsageTray\snapshots.jsonl`), so raw data is always there if you want to analyze usage patterns.

## Security and privacy

This tool asks to read your Codex/Claude sign-in credentials and automatically modifies the file that stores your OAuth token. **Understanding what it actually does matters more than the feature list** — which is also why the source is public instead of just a shrink-wrapped installer:

- **No external server**: usage data only flows between your machine, the Codex app-server, and Anthropic's official API. UsageTray runs no server of its own and sends nothing to the author or any third party. Read the three Python files under [`collectors/`](collectors/) yourself — there is no network call you can't account for.
- **Tokens never get logged or sent anywhere**: every error message is scrubbed of credential strings before it's written out; the Telegram bot token is encrypted at rest with Windows DPAPI (the same mechanism browsers use for saved passwords) under `%APPDATA%\UsageTray\`, never in plaintext.
- **Writing back credentials is the one high-risk step, and it's built conservatively**: when the Claude OAuth token expires, UsageTray calls the official refresh endpoint and writes the new token back into `.credentials.json`. This step re-reads the file right before writing and compares it against what it started with — if something else (like the `claude` CLI itself) already refreshed in the meantime, it discards its own result and uses the newer token instead of clobbering it. The write itself is atomic (temp file in the same directory, then replace), so a crash mid-write can't leave you with a corrupted credentials file.
- **You can verify this yourself, not just take my word for it**: run `python collectors/test_collect_usage_tray_contract.py` to see the tests (including cases that simulate a failed refresh and a concurrent-write race), or read [`docs/COLLECTOR-CONTRACT.md`](docs/COLLECTOR-CONTRACT.md) for the data contract spelling out exactly which fields can never appear in the output.

If you don't need that guarantee, any off-the-shelf usage display tool can handle "showing a number." UsageTray's reason to exist is that you can personally check it isn't doing anything sketchy with your sign-in credentials.

## Features

- Lives in the system tray; left-click the icon to pop the panel open. Hover shows both agents' 5-hour usage and time to reset. Starts automatically on boot.
- `Now`: used percentage and reset time for every quota window on both agents, refreshed live.
- `Trends`: two charts — 5-hour usage over the last 24 hours, and weekly usage over the last 7 days — with Claude and Codex overlaid on the same chart for direct comparison, legend showing current values.
- `Alerts`: Telegram bot setup (paste token, auto-detect chat, send a test) and threshold-based push alerts.
- Telegram two-way: proactive alerts on threshold crossings (multiple crossings in one cycle are combined into a single message); send `/usage` anytime to pull the current report (replies within ~2 minutes).

## Requirements

- Windows 10/11 (x64)
- [Python 3.10+](https://www.python.org/downloads/) with `python` on PATH (the collector is a stdlib-only Python script — no pip packages needed)
- At least one of:
  - [Codex CLI](https://github.com/openai/codex) (usage read via `codex app-server`)
  - [Claude Code](https://code.claude.com/docs/en/overview) (usage read via OAuth credentials)

## Install

1. Download the latest `UsageTray_x.y.z_x64-setup.exe` from [Releases](https://github.com/wakeuplate/usage-tray/releases) (or build from source, below) and run it.
2. Launch UsageTray from the Start menu; a tray icon appears, and it starts automatically on future boots.

### Telegram alert setup (optional)

1. Create a bot with [@BotFather](https://t.me/BotFather) and get its token.
2. Send your bot any message.
3. Open UsageTray's `Alerts` tab, paste the token → `Find my chat` to auto-detect → check "enable".
4. The token is stored encrypted with Windows DPAPI under `%APPDATA%\UsageTray\`, never in plaintext.

## Build from source

Requires Rust (MSVC toolchain), Node.js, Visual Studio C++ Build Tools, and the Windows SDK. Full steps in [docs/WINDOWS-BUILD.md](docs/WINDOWS-BUILD.md).

```powershell
cd app
npm install
npm run tauri build
# Output: app/src-tauri/target/release/bundle/nsis/UsageTray_<version>_x64-setup.exe
```

## Architecture

- **Shell**: Tauri v2 (Rust) + React/TypeScript frontend, a 336×400 borderless window docked near the tray.
- **Collector**: `collectors/collect_usage_tray.py` reads both data sources and prints sanitized JSON (contract in [docs/COLLECTOR-CONTRACT.md](docs/COLLECTOR-CONTRACT.md)):
  - Codex: local `codex app-server`'s `account/rateLimits/read` JSON-RPC method.
  - Claude: reads `%USERPROFILE%\.claude\.credentials.json`, calls the official usage API; refreshes and atomically writes back on expiry.
- **History**: `collectors/history_snapshot.py` appends to `%APPDATA%\UsageTray\snapshots.jsonl` (design in [docs/SNAPSHOT-HISTORY.md](docs/SNAPSHOT-HISTORY.md)).
- **Alerts and commands**: `collectors/telegram_bridge.py` handles threshold dedup, push alerts, and `/usage` replies.

## Tests

```powershell
python collectors/test_collect_usage_tray_contract.py
```
