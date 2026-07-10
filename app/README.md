# Limit Lens App Shell

This folder contains the first Tauri tray-shell prototype.

Current intent:

- keep the real datasource logic in `../collectors/collect_limit_lens.py`;
- expose Tauri commands for live usage, recent history, and tray tooltip updates;
- show a compact popup with horizontal usage bars;
- save sanitized JSONL history under `%APPDATA%\LimitLens\snapshots.jsonl`;
- show a compact 24-hour peak view;
- use sample data in plain browser preview when the Tauri backend is not running.

## Browser preview only

This path does not require Rust, Cargo, or Visual Studio Build Tools.

```powershell
& "C:\Program Files\nodejs\npm.cmd" run dev
```

Then open:

```text
http://127.0.0.1:1420/
```

In browser preview, the app uses sanitized usage and history samples because the Tauri backend is not running.

## Local commands

PowerShell blocks `npm.ps1` on this machine, so use `npm.cmd`.

```powershell
& "C:\Program Files\nodejs\npm.cmd" install
& "C:\Program Files\nodejs\npm.cmd" run dev
```

For the Tauri app:

```powershell
& "C:\Program Files\nodejs\npm.cmd" run tauri:dev
```

## Current local environment note

Node is installed.

Rust, Cargo, and WebView2 are installed.

The native Tauri shell is currently blocked because Microsoft Visual Studio Build Tools with MSVC and the Windows SDK are not installed. The React/Vite frontend build and the Rust formatting/metadata checks pass.

After installing the `Desktop development with C++` workload, run:

```powershell
& "C:\Program Files\nodejs\npm.cmd" run tauri:dev
```

## Tray behavior

- Starts hidden and does not create a taskbar button.
- Left click opens or closes the compact panel.
- Right click opens the Show/Quit menu.
- The panel is positioned next to the tray icon and hides when it loses focus.
- Starting Limit Lens again focuses the existing instance instead of creating another tray icon.
- Tooltip shows current Codex and Claude 5-hour remaining percentages.
- A background reading is taken every 5 minutes.

## History behavior

- Stores only sanitized percentages, reset times, source labels, availability, and safe error codes.
- Stores immediately when a visible value changes.
- Otherwise stores one reading every 5 minutes.
- Keeps malformed or interrupted final lines from blocking future writes.
- The `24h` view reads a bounded recent history set and displays peak usage.

## Safety

The app shell calls the collector and expects sanitized JSON. Collector and history scripts are bundled as Tauri resources for release builds.

It must not store tokens, cookies, session keys, raw credentials, raw prompts, or raw API responses.
