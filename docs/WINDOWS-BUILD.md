# UsageTray Windows Build

Updated: 2026-07-11

The native build requires the components below. The current development machine has them installed.

## One-time installation

Install **Visual Studio Build Tools 2022**.

In the installer, select:

```text
Desktop development with C++
```

Keep these components selected:

- MSVC build tools for x64/x86;
- Windows 11 SDK or Windows 10 SDK.

No full Visual Studio editor is required.

## Run the tray app

Open a new PowerShell window after installation:

```powershell
cd D:\claude-projects\usage-tray\app
& "C:\Program Files\nodejs\npm.cmd" run tauri:dev
```

Expected behavior:

1. UsageTray starts hidden.
2. A tray icon appears.
3. Left click opens the compact panel next to the tray.
4. Clicking elsewhere hides the panel.
5. Right click shows **Show UsageTray** and **Quit**.
6. The tooltip shows Codex and Claude 5-hour remaining percentages.
7. History is written to `%APPDATA%\UsageTray\snapshots.jsonl`.

## Build the installer

After the development run is confirmed:

```powershell
cd D:\claude-projects\usage-tray\app
& "C:\Program Files\nodejs\npm.cmd" run tauri:build
```

The installer output will be under:

```text
D:\claude-projects\usage-tray\app\src-tauri\target\release\bundle\
```

## Current Claude sign-in

The latest live test returned `claude_auth_expired`.

Before final runtime verification, run:

```powershell
& "$env:USERPROFILE\.local\bin\claude.exe" auth login
```

UsageTray never stores the Claude access token in its own data directory. With Claude token auto-refresh enabled (the default), it may update the existing Claude Code credential and retains one adjacent `.credentials.json.bak` backup. Disable this in `Alerts → App settings` for read-only collection.
