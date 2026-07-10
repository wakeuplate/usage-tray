# Task: Add autostart plugin and build the release NSIS installer

Allowed write paths: D:\claude-projects\limit-lens
Forbidden paths: C:\Users\user\.claude, C:\Users\user\.agents, D:\icloud, anything else.
Do NOT install the built installer or modify the Windows registry/startup entries yourself — building the .exe is the deliverable; installation is the user's step.

## Goal & motivation

UsageTray (Tauri v2 tray app in app/) currently only runs in dev mode and does not start on boot. The user wants: install once, auto-start on every boot, zero manual steps. Add the official autostart plugin (enabled by default on app setup) and produce the NSIS installer.

## Steps

1. In `app/src-tauri/Cargo.toml`, add dependency: `tauri-plugin-autostart = "2"` (next to the existing tauri-plugin-* lines).
2. In `app/src-tauri/src/lib.rs`:
   - register the plugin on the builder (near the existing `.plugin(tauri_plugin_single_instance...)`):
     `.plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, None))`
   - in the `.setup(...)` closure, enable autolaunch (ignore errors, this must not break startup):
     ```rust
     use tauri_plugin_autostart::ManagerExt;
     let _ = app.autolaunch().enable();
     ```
     Follow the file's existing style; put the `use` at the top of the file with the other imports.
3. Check `app/package.json` scripts for the build script name (probably `tauri build` via a `tauri` script). Run the release build from `app/`: `npm run tauri build` (or `npx tauri build` if no script). This takes several minutes; wait for it.
4. If the build fails, stop and report the exact error verbatim. Do not guess-fix beyond obvious missing-import compile errors in the code you just added.

## Verify

- Build succeeds; report the full path and exact size (bytes and MB) of the produced installer under `app/src-tauri/target/release/bundle/nsis/` and of the bare exe `app/src-tauri/target/release/*.exe`.
- `git status --short` shows only Cargo.toml, Cargo.lock, lib.rs changed (build outputs are untracked; do NOT commit).

## Report format

Conclusion first, ≤30 lines; every claim with evidence (command output or file:line); installer path + sizes explicitly; uncertainties marked.
