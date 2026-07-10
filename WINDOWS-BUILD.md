# Limit Lens Windows Build

Updated: 2026-07-09

## Current blocker

The app code, frontend build, Rust formatting, Tauri metadata, and local tests pass.

The native tray app cannot be compiled on this computer yet because these Microsoft components are missing:

- MSVC C++ build tools;
- Windows SDK;
- `link.exe`.

Rust and WebView2 are already installed.

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
cd D:\claude-projects\limit-lens\app
& "C:\Program Files\nodejs\npm.cmd" run tauri:dev
```

Expected behavior:

1. Limit Lens starts hidden.
2. A tray icon appears.
3. Left click opens the compact panel next to the tray.
4. Clicking elsewhere hides the panel.
5. Right click shows **Show Limit Lens** and **Quit**.
6. The tooltip shows Codex and Claude 5-hour remaining percentages.
7. History is written to `%APPDATA%\LimitLens\snapshots.jsonl`.

## Build the installer

After the development run is confirmed:

```powershell
cd D:\claude-projects\limit-lens\app
& "C:\Program Files\nodejs\npm.cmd" run tauri:build
```

The installer output will be under:

```text
D:\claude-projects\limit-lens\app\src-tauri\target\release\bundle\
```

## Current Claude sign-in

The latest live test returned `claude_auth_expired`.

Before final runtime verification, run:

```powershell
& "$env:USERPROFILE\.local\bin\claude.exe" auth login
```

Limit Lens never stores the Claude access token. It only reads the existing Claude Code credential when collecting usage.
