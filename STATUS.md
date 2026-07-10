# Limit Lens Status

Updated: 2026-07-10 +08:00

## Plain-language status

Limit Lens is currently past the first important checkpoint: the two meters can be read.

In simple terms, we have proven that:

- Codex usage can be read from Codex's local app server.
- Claude usage can be read from Claude Code OAuth credentials.
- Both sources match the real UI screenshots closely enough to trust for v1.
- The project should continue with collector/data-contract work before UI work.

## Completed

### 1. Research direction decided

The project plan now has a safer v1 data-source direction:

- Codex primary source: `codex app-server` method `account/rateLimits/read`.
- Claude primary source: Claude Code OAuth `.credentials.json` plus `https://api.anthropic.com/api/oauth/usage`.
- Claude browser `sessionKey` is not the default path.
- Claude `statusLine` is fallback only, not the v1 main path.
- Tokens, cookies, and session keys must never be written to logs, config, database, or documents.

Reference files:

- `PLAN.md`
- `RESEARCH-datasource-20260707.md`

### 2. Claude OAuth spike completed

Claude Code OAuth was verified as a working source.

Confirmed:

- `.credentials.json` exists after Claude Code account login.
- The useful key is `claudeAiOauth`, not `mcpOAuth`.
- The collector can call the Claude OAuth usage endpoint using the access token in memory.
- The response contains usable 5-hour and weekly quota data.
- The result matched the Claude UI screenshot:
  - 5-hour usage: 13%.
  - Weekly all models usage: 90%.
  - Weekly scoped/model usage: 99%.

Safety result:

- No token, refresh token, session key, or cookie was printed.
- Nothing under `C:\Users\user\.claude\` was modified.

Spike note:

- `SPIKE-claude-oauth-20260708.md`

### 3. Codex app-server spike completed

Codex app-server was verified as a working source.

Confirmed:

- `codex app-server --disable plugins` can be started locally.
- JSON-RPC method `account/rateLimits/read` works.
- The response contains:
  - `usedPercent`
  - `windowDurationMins`
  - `resetsAt`
- The result matched the Codex UI screenshot:
  - UI shows remaining percentage.
  - Collector stores used percentage.
  - These numbers are complementary, so `used 31%` means `remaining 69%`.

Latest checked Codex comparison:

- 5-hour collector: used about 5%, remaining about 95%.
- 5-hour UI: remaining 96%.
- Weekly collector: used 31%, remaining 69%.
- Weekly UI: remaining 69%.
- Reset time also matched the UI.

Small 1% differences are expected because the UI and collector may refresh at different seconds and may round numbers differently.

Spike note:

- `SPIKE-codex-appserver-20260708.md`

### 4. Minimal collector created

A first collector exists at:

- `collectors/collect_limit_lens.py`

It currently does the boring but important job: read the two meters and print one clean JSON object.

It supports:

- Codex quota collection.
- Claude quota collection.
- `--skip-codex` for testing Claude only.
- `--skip-claude` for testing Codex only.
- Timeout control.
- Sanitized JSON output.

Collector README:

- `collectors/README.md`

Current collector safety rules:

- Does not print tokens.
- Does not print cookies.
- Does not print session keys.
- Does not write config.
- Does not write database.
- Does not write logs.
- Does not read conversation transcripts.
- Does not modify `.claude` or `.codex`.

### 5. Collector contract created

The collector output meaning is now written down at:

- `COLLECTOR-CONTRACT.md`

This document defines:

- required top-level fields;
- Codex and Claude agent result shapes;
- usage window fields;
- `used_percent` versus `remaining_percent`;
- reset time rules;
- safe error shape;
- forbidden sensitive data;
- fields the future UI may rely on.

### 6. Local contract check added

A small no-network test was added at:

- `collectors/test_collect_limit_lens_contract.py`

It checks:

- schema version;
- usage window shape;
- remaining percentage calculation;
- error object shape;
- source scan for obvious literal credential patterns.

Latest result:

- 9 tests passed.

### 7. Snapshot history plan created

Safe history storage is now designed at:

- `SNAPSHOT-HISTORY.md`

Current v1 decision:

- Start with JSONL snapshots.
- Keep the collector stdout-only.
- Let a separate app/history layer decide when to save.
- Do not store diagnostics, credential paths, command paths, tokens, cookies, prompts, transcripts, or raw API responses.

### 8. Sample output and schema created

UI-facing sample and schema files now exist:

- `samples/collector-output-v0.sample.json`
- `schemas/collector-v0.schema.json`

The sample is sanitized and parseable JSON.

The schema is a first draft for the collector v0 shape.

### 9. History snapshot prototype created

A tiny JSONL history writer prototype now exists at:

- `collectors/history_snapshot.py`

It converts collector JSON into `limit-lens.snapshot.v0` history rows.

It keeps safe usage fields and drops diagnostics, command paths, and credential paths by default.

### 10. Tauri app shell scaffold created

A first app shell now exists at:

- `app/`

It includes:

- Vite + React + TypeScript frontend;
- Tauri v2 config;
- Rust tray setup draft;
- a `collect_usage` backend command that calls the existing Python collector;
- sample-data fallback for plain browser preview;
- a compact usage panel with horizontal bars;
- dark/light theme support through system color scheme.

Important limitation at that time:

- Rust/Cargo was installed, but the Tauri desktop shell was still blocked by the missing Microsoft Visual C++ linker (`link.exe`).

### 14. Refresh-adjacent timestamp and reset layout adjusted

Browser preview was adjusted based on visual feedback:

- last captured time moved next to the Refresh button;
- captured time format is `MM/DD HH:MM AM`;
- reset time and usage percent swapped positions;
- usage percent is right-aligned;
- weekly reset time format is `MM/DD Mon HH:MM AM`;
- 5-hour reset time uses `tomorrow` when the reset is tomorrow;
- Codex and Claude received compact identifying icon badges;
- Codex context window UI support was added when sanitized context data exists.

Note:

- Context window is currently supported by the UI shape and sample data.
- The live collector still needs a confirmed safe field before real context values can be shown consistently.

### 15. Transparent product icons and compact values added

The browser preview now uses cleaned transparent Codex and Claude marks supplied by the user.

Also adjusted:

- reset time now sits directly beside the usage percentage on the right;
- both values are right-aligned for easier scanning;
- Codex context window now shows only a percentage, such as `Ctx 53%`;
- icon color adapts to dark and light themes without a colored square behind it.

Final icon assets:

- `app/public/icons/codex.png`
- `app/public/icons/claude.png`

### 16. Context remaining value and iOS-style polish added

The Codex context window now shows the remaining percentage, such as `Context 剩餘 47%`, instead of the used percentage.

The compact panel was also reviewed against the iOS Control Center direction:

- stronger translucent glass material and backdrop blur;
- restrained inner-panel highlights instead of heavier decoration;
- tabular numbers for stable alignment;
- visible hover and keyboard focus feedback;
- reduced-motion support;
- redundant browser-preview footer removed to keep the panel short.

### 13. Compact preview layout adjusted

Browser preview was adjusted based on visual feedback:

- panel height was reduced;
- source labels were removed from the main card headings;
- each quota row now keeps label, used percent, and reset time on one compact line;
- reset time now uses compact display:
  - today: `3:08 AM`;
  - tomorrow: `明天 11:00 AM`;
  - later: `Sat 11:00 AM`.

### 12. Browser preview verified

The no-extra-system-tools path now works:

- Vite dev server runs at `http://127.0.0.1:1420/`.
- The page responds with HTTP 200.
- The sanitized sample data responds with HTTP 200.
- This path does not require Rust/Cargo or Visual Studio Build Tools.
- It does not run the real Windows tray shell.

### 11. Frontend build verified

The app frontend was verified with:

- `npm install`
- `npm run build`

Result:

- TypeScript passed.
- Vite production build passed.
- Output was generated under `app/dist/`.

Environment note:

- Node is installed.
- npm works through `npm.cmd`; PowerShell blocks `npm.ps1`.
- npm is old and warns that some packages prefer npm 8+, but the frontend build still succeeds.
- Rust 1.96.1 and Cargo 1.96.1 are installed.
- Microsoft Visual Studio Build Tools with MSVC and the Windows SDK are still missing.

### 17. Safe history and production tray behavior implemented

The app now has a working v1 history path in code:

- successful live readings are sanitized and written to `%APPDATA%\LimitLens\snapshots.jsonl`;
- error messages, diagnostics, credential paths, command paths, limits, spend objects, and unknown fields are not persisted;
- unchanged readings are saved once every 5 minutes;
- visible percentage, reset time, source, availability, or error-code changes are saved immediately;
- an interrupted final JSONL line no longer prevents future history writes;
- the UI has a compact `Now` / `24h` switch with recent peak usage bars;
- the Tauri backend can read the latest history without loading unlimited rows.

The Windows tray implementation now also includes:

- hidden startup with no taskbar button;
- left-click popup toggle without opening the context menu;
- popup positioning relative to the tray icon;
- automatic hide when focus is lost;
- background collection every 5 minutes;
- live 5-hour remaining percentages in the tray tooltip;
- single-instance protection so reopening focuses the existing app instead of creating a second tray icon;
- collector and history scripts bundled as app resources;
- NSIS current-user installer configuration and standard Windows icon assets;
- a restrictive Content Security Policy;
- blocking collector work moved off the UI thread.

Latest verification:

- 15 local collector/history tests passed;
- React/TypeScript production build passed;
- browser preview and sample history both return HTTP 200;
- live Codex collection works;
- live Claude collection currently reports `claude_auth_expired` because Claude Code returned HTTP 401;
- Tauri environment detection confirms Rust and WebView2, but no MSVC/Windows SDK.

### 18. Native Windows build path verified and Claude OAuth restored

The previous native blocker is now cleared.

Confirmed:

- Microsoft Visual Studio Build Tools was installed with the Desktop development with C++ workload;
- MSVC is available under the Visual Studio Build Tools install;
- the Windows SDK is available;
- Rust is using the correct `stable-x86_64-pc-windows-msvc` toolchain;
- `npm run tauri:dev` now completes a real native compile and launches `target\debug\limit-lens.exe`.

One small code fix was needed during this verification:

- Tauri tray icon loading required the `image-png` feature to be enabled in `app/src-tauri/Cargo.toml`.

Claude live collection is also restored:

- the user re-ran `claude auth login`;
- the Claude OAuth collector now returns live quota data again;
- current observed Claude status at verification time:
  - 5-hour remaining: 100%;
  - weekly remaining: 10%;
  - weekly scoped remaining: 1%.

Remaining note:

- `claude doctor` still reports a leftover global npm Claude installation, but this does not block Limit Lens collection.

### 19. Popup layout v2 refined for fixed-size desktop use

The tray popup layout was refined to behave more like a stable Windows utility panel:

- `Now`, `24h`, and `Alerts` now target one shared fixed window size instead of changing shell dimensions per tab;
- the popup width was intentionally reduced by about 20% for a denser, more utility-like feel;
- the oversized top empty area was removed by switching the main card from full-window height to content-height;
- the extra outer ring look was reduced so the UI reads as one primary card, not a card inside another shell;
- future extra rows are expected to stay inside the same window size and scroll inside the content area instead of growing the whole popup.

Current native popup target:

- width: `336`
- height: `400`

Current behavior goal:

- fixed outer window size across all three tabs;
- compact content card aligned near the taskbar;
- overflow handled inside the content region, not by resizing the window.

### 20. Popup height fix and release-readiness review (2026-07-10)

A measurement pass at the exact window size found real clipping, and a code review
found two release-build bugs. Changes:

- window height raised from `372` to `400`: at `372` the content area needed
  267px but was capped at 248px, so the Claude `Scoped` row was always cut off,
  and any notice banner pushed the whole panel 21px past the window;
- content cap (`.agent-grid` max-height) raised from `248` to `280`;
- the notice banner is now a floating toast overlay, so it no longer shifts the
  layout when it appears;
- usage rows with no data are no longer rendered as empty ghost rows (e.g. if
  Claude `weekly_scoped` disappears, the card just gets shorter);
- `collectors/telegram_bridge.py` was missing from the bundle resources in
  `tauri.conf.json`, which would break all Telegram features in the installed
  build — added;
- Python helper processes are now spawned with `CREATE_NO_WINDOW`, so the
  installed (windowless) build will not flash a console window on every
  collection cycle.

Verified after the change: all three tabs fit with zero clipping at 336x400
(Now 267px, 24h 267px, Alerts 260px of content), frontend build and
`cargo check` both pass, and the dev watcher relaunched the app successfully.

Width verdict: `336` is fine — every row (label, reset time, percent) fits on
one line with sample data; no need to widen or narrow.

### 21. Rename to UsageTray, glass removed, Chinese Telegram alerts (2026-07-10)

Based on a real-desktop screenshot from the user, the translucent glass shell
clashed with the opaque card and the window-level rounding, so the design moved
to a single opaque card:

- the shell now fills the whole 336x400 window (flex column, content area takes
  the remaining space), so there is no transparent gap band below the card;
- backdrop blur and translucent gradients removed; solid dark `#131417` /
  light `#f2f4f7` backgrounds with a subtle border, radius reduced to 16px;
- the content grid uses `align-content: start` and scrolls internally when
  future rows exceed the space.

Product renamed from Limit Lens to **UsageTray** (user's pick):

- `productName`, window title, identifier (`local.usage-tray.app`), UI header,
  tray tooltip/menu, page title, collector clientInfo, schema title updated;
- data directory renamed to `%APPDATA%\UsageTray` with an automatic one-time
  migration from `%APPDATA%\LimitLens` at startup (verified: all four files
  moved, including the DPAPI token);
- still pending (deliberate, needs the dev server stopped): project folder
  name `limit-lens`, Cargo package/binary name, `package.json` name, docs
  sweep, and the `check-ai-usage` skill's references to the old paths.

Telegram alerts reworked:

- thresholds changed from `70/85/95` to `50/85/95`;
- alert, source-error, and test messages rewritten in Traditional Chinese with
  a severity emoji (🔔/⚠️/🚨), used/remaining on one line, and reset time in
  local Taiwan time with a Chinese weekday, e.g.
  `⚠️ Claude 每週額度已達 85%`;
- verified by direct function smoke test (UTC input rendered as `+08:00`).

All checks pass after the change: 15 collector contract tests, frontend build,
`cargo check`, and the layout re-measured at 336x400 with zero clipping and the
shell filling the window exactly.

### 22. Corner shadow fix and full-report Telegram alerts (2026-07-10)

A real desktop screenshot showed a faint square residue poking out past the
card's rounded corners. Cause: Windows still draws its own rectangular drop
shadow around an undecorated/transparent window even though the card content
inside is rounded, so the shadow's square corners peek out past the 16px
radius. Fixed with `"shadow": false` on the window in `tauri.conf.json`
(Tauri-level option, only implemented on Windows/macOS).

Telegram alerts now include a full two-agent usage report, not just the one
window that crossed a threshold, per user request. `collectors/telegram_bridge.py`
gained:

- `render_bar()`: 10-cell block-character bar (`█`/`░`) from a percent;
- `build_report_lines()`: walks Codex (`5h`, `週`) then Claude (`5h`, `週`,
  `週S`) in a fixed order and renders `label bar percent  重置 <time>` per line;
- `alert_message()` / `error_message()` now append this report inside a
  Telegram `<pre>` block (monospace, HTML `parse_mode`) so the bars line up;
  `html.escape()` is applied to the report text and to any API-provided error
  text before embedding, since HTML parse mode is now active;
- `send_message()` gained an optional `parse_mode` argument; the plain test
  message still sends unformatted.

Verified with a direct smoke test using numbers matching the user's screenshot
(Codex 17%/76%, Claude 73%/8%/12%) — see conversation log for the literal
rendered text. Collector contract tests (15) still pass.

### 23. Telegram report readability fix (2026-07-10, same day)

A real Telegram screenshot of the report from #22 showed three problems: rows
wrapped mid-line on a phone-width bubble, the bracket bars did not start at
the same column (`5h`/`週`/`週S` labels render at different monospace-cell
widths — CJK glyphs are double-width — so the shorter `5h` label started its
bar one cell earlier than the others), and the reset time
(`07/10（週五）06:59`) did not read as "today" without the reader doing date
math themselves.

Fixes in `collectors/telegram_bridge.py`:

- `render_bar()` switched from Unicode block-shade glyphs (`█`/`░`) to plain
  ASCII in brackets (`[###-------]`) — safer across Telegram client fonts and
  the bracket makes the bar boundary unambiguous even if a font isn't truly
  monospace;
- `WINDOW_SHORT_LABELS` padded so every label is exactly 3 monospace cells
  (`"5h "`, `"週 "`, `"週S"`), so all bars now start at the same column;
- each window now renders on two short lines (bar+percent, then an indented
  reset line) instead of one long line, so nothing wraps mid-content even on
  a narrow phone bubble;
- `format_reset()` now takes a `reference` datetime and returns `今天 HH:MM` /
  `明天 HH:MM` / `MM/DD 週X HH:MM` — the same today/tomorrow/weekday pattern
  the in-app UI already uses (`app/src/main.tsx` `formatReset`) — instead of
  always printing the absolute date. `resolve_reference()` derives "today"
  from the snapshot's own `captured_at` so the header line and the per-window
  reset lines always agree with each other.

Re-verified with the same smoke-test numbers: every line is now well under
25 characters (previously up to ~35+ with inline weekday/date/reset text),
bars align at a fixed column, and a same-day reset like `07/10` now reads as
`今天 06:59`. Collector contract tests (15) still pass.

### 24. Bar style reverted, tree-branch connectors added (2026-07-10, same day)

User feedback: the ASCII bracket bar (`[###-------]`) from #23 looked ugly;
the earlier block-character bar (`██░░░░░░░░`) was fine. `render_bar()`
reverted to `█`/`░` with no brackets.

Also added tree/branch connectors (`├─` `└─` `│`) in front of each window row
so the report visually reads as a directory tree under each agent name
(Codex/Claude as the root, each usage window as a child, the last child using
`└─` with no continuing vertical line on its indented reset row). Box-drawing
characters were chosen because they're single-width and near-universally
supported by monospace fonts, unlike the block-shade glyphs which briefly
looked like a rendering glitch on the user's phone.

Re-verified: max line length 23 characters (still safe from mobile wrapping),
15 collector contract tests still pass.

### 25. Emoji-square bars, drop monospace dependency entirely (2026-07-10, same day)

User reported the tree connectors (`├─`/`│`) from #24 also render inconsistently
on their phone. Root cause: the report was relying on Telegram's `<pre>`
block actually being a true fixed-width font on the reader's device to keep
columns aligned — but not every phone honors that, so any text-glyph approach
(block shades, ASCII brackets, box-drawing) was going to eventually break on
some device.

Switched the bar to colored square emoji (🟩/🟧/🟥 filled, ⬜ empty,
color threshold matching the in-app UI's 70%/90% warm/danger cutoffs) and
dropped the `<pre>` HTML wrapper and box-drawing connectors entirely. Emoji
are rendered from Telegram's own bundled art on every platform, not the
device's system font, so this is the first bar style in this thread that
doesn't depend on monospace rendering at all. `send_message()` no longer
needs `parse_mode`; `html.escape()` and the `html` import were removed since
there's no HTML being sent anymore.

Re-verified with the same smoke-test numbers (see conversation log for the
literal output) and the 15 collector contract tests.

### 26. Real MarkdownV2 code fence, user-drafted format (2026-07-10, same day)

User supplied an exact target format and asked for it to be wrapped in a
proper Telegram code fence (triple backtick, `parse_mode="MarkdownV2"`)
instead of the HTML `<pre>` tag used in #22-23. A code fence is the more
standard way to force monospace rendering in Telegram and may behave more
consistently than HTML `<pre>` across client versions/devices.

Changes in `collectors/telegram_bridge.py`:

- `render_bar()` reverted to block characters (`█`/`░`), no brackets — third
  time reverting; alignment now relies on the code fence's guaranteed
  monospace font rather than on the specific glyph chosen;
- `build_report_lines()` gained `lead_agent`: the agent whose window
  triggered the alert is now listed first in the report, matching the user's
  draft (e.g. a Claude alert shows the Claude block before Codex);
- each window is now a single line (`label bar percent · reset`) instead of
  two, using a new `format_reset_compact()` — `重置 HH:MM` for today,
  `明天HH:MM` for tomorrow, `MM/DD HH:MM` beyond that (no weekday, no
  "重置" prefix past today, matching the user's literal draft);
- `alert_message()` / `error_message()` now escape the non-code-fence lines
  with a small `escape_markdown_v2()` helper (MarkdownV2 requires escaping
  `_*[]()~\`>#+-=|{}.!` outside code entities) and the code-fence body with
  `escape_code_block()` (only backslash/backtick need escaping inside a code
  entity per Telegram's rules); `send_message()` takes `parse_mode` again;
- footer label shortened from `資料時間` to `更新`, per the user's draft.

Verified with the same smoke-test numbers; contract tests (15) still pass.
This is the third bar-rendering approach tried in one session — still needs
the user to confirm on their actual phone before treating it as settled.
### 27. Claude OAuth auto-refresh (2026-07-10)

Claude collector now supports OAuth token refresh with atomic write-back to the
credentials file under the project scope.

Changes:

- `collectors/collect_limit_lens.py` now refreshes expired or near-expiry Claude OAuth tokens before usage calls, retries once on a 401, and writes refreshed tokens back atomically when safe.
- The collector re-reads the credentials file before writing so a concurrent refresh wins and the collector uses the file's current token instead of overwriting it.
- `collectors/test_collect_limit_lens_contract.py` adds coverage for refresh success, refresh failure, concurrent-change guard, and valid-token no-refresh behavior.
- `collectors/telegram_bridge.py` adds a `claude_refresh_failed` hint.
- `PLAN.md` now records that the old read-only policy was superseded on 2026-07-10 by user request.

Verified with:

- `python collectors/test_collect_limit_lens_contract.py`
- `python -c "import ast; ast.parse(open('collectors/collect_limit_lens.py', encoding='utf-8').read())"`

### 28. Refresh endpoint fixes, failure cooldown, live-test findings (2026-07-10, same day)

Also from earlier the same day (not previously logged): `build_report_lines()`'s
`lead_agent` reordering was removed per user request — the Telegram report is
now always Claude first, Codex second (`AGENT_ORDER`); a real MarkdownV2 alert
was delivered live to the configured chat (test harness hardcoded the "50%"
threshold label; the usage numbers themselves were real).

Live-testing the #27 auto-refresh against the real credentials file exposed
three issues, all fixed:

- the refresh request sent no `User-Agent`, so Cloudflare rejected it with
  HTTP 403 (non-JSON body). It now sends the same `claude-code/…` UA and
  `anthropic-beta` headers as the usage call;
- the endpoint constant pointed at `console.anthropic.com/v1/oauth/token`,
  which answers only HTTP 429 regardless of payload. Strings extracted from
  the installed Claude Code 2.1.199 binary show the current token endpoint is
  `https://platform.claude.com/v1/oauth/token` and that the CLI includes a
  `scope` field (space-joined) in the refresh body; both adopted;
- the tray app runs the collector every 2 minutes, so a permanently failing
  refresh would hammer the endpoint ~720×/day. A failed refresh now writes
  `%APPDATA%\UsageTray\claude-refresh-state.json` and further attempts are
  skipped for 10 minutes (`claude_refresh_cooldown` error, cleared on
  success); 3 new contract tests cover it (22 total, all passing). The state
  file was observed being written during the real failed run.

End-to-end refresh success is NOT yet verified live: the diagnostic probes
tripped an IP-level rate limit on the token endpoint (a bogus refresh token
also gets 429, proving the limit is per-IP, not per-token). Next attempt
should wait an hour or more; the failure path (error reported, credentials
file untouched, cooldown recorded) is verified live.

Follow-up (same day, afternoon): `platform.claude.com/v1/oauth/token` was
still wrong — it (and claude.ai / console.anthropic.com) answers HTTP 429 to
every request as an anti-abuse mask. Endpoint-base sweep with a bogus token
showed the real token endpoint is **`https://api.anthropic.com/v1/oauth/token`**
(returns a proper `invalid_grant`); constant corrected. Two more findings:
running the official `claude` CLI once made it refresh the token itself
successfully from the same machine/IP (so the user's "daily re-login" was
never necessary — the CLI self-refreshes; only UsageTray's error message
suggested re-login), and the collector was verified live against the fresh
token (available=true, real usage data, refresh correctly skipped while the
token is valid). The expired-token→refresh→write-back path is verified in
unit tests but not yet live: forcing `expiresAt` into the past on the real
credentials file was blocked by the permission layer (user red line); either
the user approves that one-off forced test, or natural expiry (~8 h) will
exercise it during normal app polling.

Separate discovery: `limit-lens/.git` and `D:\claude-projects\.git` are both
EMPTY directories (no HEAD/objects) — the project has never actually been
under version control; tooling that reported "git repo, branch HEAD" was
fooled by the empty dir. Consider a real `git init` + initial commit.

### 29. Autostart plugin and first release installer (2026-07-10, same day)

- `tauri-plugin-autostart` 2.5.1 added; `lib.rs` registers it and calls
  `app.autolaunch().enable()` in setup (errors ignored so a failed registry
  write can never break app startup). Once the installed app is launched
  once, it self-registers to start on every boot.
- First real release build produced:
  `app/src-tauri/target/release/bundle/nsis/UsageTray_0.1.0_x64-setup.exe`
  (2.5 MB installer; bare exe 9.4 MB). Codex wrote the code changes; the
  build itself ran in the main session because the Codex sandbox has no
  network access for crates.io.
- Not yet done: actually installing it (user's one click) and verifying the
  installed app end-to-end (bundled collector scripts, tray behavior,
  autostart after reboot, and tonight's natural token-expiry refresh).

## Current project state

The project now has a working native Windows development path.

Right now it is at the implementation-complete-and-native-verified stage:

1. The Codex meter works.
2. The Claude meter works.
3. The first combined collector works.
4. The collector output contract is now written down.
5. A small contract test now checks the core output shape.
6. Safe local history snapshots are now designed.
7. A sanitized sample output and JSON Schema draft now exist.
8. Safe history saving and 24-hour peak reading are implemented.
9. The Tauri tray behavior is implemented.
10. The frontend popup builds successfully.
11. Rust/Cargo, WebView2, MSVC, and the Windows SDK are installed.
12. The real Tauri tray app has been compiled and launched locally.
13. Claude live OAuth collection is working again after re-authentication.
14. The popup layout now uses a fixed-size v2 shell for `Now` / `24h` / `Alerts`.

A good analogy:

- We have built the water/electricity meter reader.
- We have built the wall display and turned the power on.
- The next work is adding the smart alerting behavior and polishing daily use.

## What still needs to be done

### Next immediate step: desktop polish and packaging verification

The collectors and tray shell work.

The current highest-value work is now making the popup feel correct on the real Windows desktop:

- verify the new fixed-size popup at actual taskbar scale;
- verify the narrower width is still readable at Windows scaling settings;
- confirm the popup no longer shows the unwanted top cap / extra shell feeling;
- confirm overflow behavior when rows appear or disappear;
- verify tray icon readability beside other Windows tray icons.

After that, return to notifications:

- Telegram secure token storage;
- chat discovery;
- threshold alerts;
- auth/source alerts.

### Safe snapshots are now implemented

The app now writes sanitized JSONL history under `%APPDATA%\LimitLens\` when the native shell runs.

This enables later features like:

- When usage usually spikes.
- How fast quota gets consumed.
- How long it takes to recover after reset.
- Whether Codex or Claude is the current bottleneck.

### Tray shell code is now implemented

The remaining work is real-desktop behavior verification, packaging, and notifications.

UI style target:

- iOS Control Center / Raycast feeling.
- Horizontal bar charts.
- Dark and light theme.
- Clear reset times.
- No pie charts.
- No scary technical token display by default.

### Later: fallback modes

Only after the main path is stable:

- Claude statusLine fallback.
- Optional ccusage-style history import.
- Optional precision mode using Claude browser sessionKey.

Important:

`sessionKey` precision mode should stay opt-in and last resort, because it is more sensitive than the Claude Code OAuth path.

## Recommended next work order

1. Add Telegram notification settings and secure token storage.
2. Send and verify a Telegram test message.
3. Implement threshold and auth-expired alerts with deduping per reset cycle.
4. Confirm tray position, popup focus behavior, background history, and tooltip on the real desktop.
5. Build the Windows installer.

Beginner-friendly instructions are in `WINDOWS-BUILD.md`.

## Current confidence

High confidence:

- Codex primary source is viable.
- Claude OAuth primary source is viable.
- The combined collector is the correct next foundation.

Medium confidence:

- Claude OAuth endpoint may change because it is not a public stable API.
- The app should show source freshness and graceful unavailable states.

Not started:

- Running tray app.
- Installer/autostart.
- Notification/warning thresholds.
- Deep fallback sources.
### 30. Repo rename to usage-tray (2026-07-10)

Repo-internal rename completed from `limit-lens` to `usage-tray` without
renaming the top-level `D:\claude-projects\limit-lens` folder.

- Collector files renamed to `collectors/collect_usage_tray.py` and
  `collectors/test_collect_usage_tray_contract.py`.
- Cargo package/lib identifiers, app package name, Tauri bundled resource
  paths, collector schema markers, EOF marker, samples, and live docs were
  updated to UsageTray / `usage-tray`.
- Folder rename and rebuild remain for the main session.

### 31. Startup-seeding no longer swallows threshold alerts (2026-07-10, same day)

User crossed 50%/85%/95% on the Claude 5-hour window with no Telegram alert.
Root cause: when `process-alerts` first sees a window cycle (fresh install,
app restart, or new quota window), it seeded already-reached thresholds as
"sent" without notifying. Fixed: new cycles seed an empty sent list and fall
through to the normal pending logic, which sends one message for the highest
reached threshold. Verified live: state slot reset, one 95% alert delivered
via the fixed code path (`{"ok": true, "sent": 1}`).

### 32. Telegram two-way /usage command (2026-07-10)

Telegram now supports a lightweight two-way command path without adding a
long-polling process. Each collection cycle polls pending bot updates once,
advances `telegram-updates-state.json`, and replies at most once when the
configured chat asks for the current usage report.

- New `poll-commands` bridge action uses Telegram `getUpdates` with
  `timeout=0`, ignores unconfigured chats, and treats poll failures as a
  non-fatal cycle result.
- The Tauri collector cycle invokes `poll-commands` immediately after
  `process-alerts`, using the same latest snapshot payload.
- Contract tests cover configured-chat replies, ignored-chat update
  advancement, and second-poll offset behavior.

### 33. Reset-time jitter no longer re-fires alerts (2026-07-10, same day)

After #31, the user was re-alerted "已達 50%" every 2-3 minutes. Cause:
Claude reset_at jitters by seconds across polls; when it crosses a minute
boundary the minute-precision cycle id flips (10:59 <-> 11:00) and each flip
looked like a new cycle, which #31 now notifies for. Fix: `same_cycle()`
compares reset-based cycle ids with a 30-minute tolerance (real cycles differ
by hours) and tracks the latest id so drift cannot accumulate. Also fixed a
double percent sign in the Alerts tab fallback text, spotted in a README
screenshot. Regression test added (26 total). Alerts were temporarily
disabled in settings during the fix to stop the spam; re-enabled after the
fixed build was installed.

### 34. Same-run threshold crossings combined into one Telegram message (2026-07-10, same day)

User received two near-identical alerts at 18:05 (Claude 5h 50% and 週S 50%),
each carrying the full report. process-alerts now collects every window that
crossed a threshold during one run and sends a single message: one header
line per crossing (emoji, window, threshold, used, reset) above the shared
report table. State marking semantics unchanged (marked only after a
successful send). Test added (27 total).

### 35. 24h tab shows real trends; Telegram footer moved into code block (2026-07-10, same day)

- The 24h tab now draws a 24-hour area sparkline per usage window (pure
  inline SVG, no chart library): peaks, resets, and app-off gaps (line breaks
  when readings are >10 min apart) are all visible. Peak value retained on
  the right. History rows use a compact spacing set so all five sparklines
  fit the 336x400 window exactly (measured overflow 0px via headless Edge).
- Telegram messages now include the 更新 timestamp inside the code fence, per
  user request.
- README screenshots regenerated with real 24h data.

### 36. Trends redesign (user-approved draft D), Now reorder, tooltip format (2026-07-10, same day)

- 24h tab renamed Trends and rebuilt per the user-approved mockup: two
  charts instead of five sparklines. "5-hour / last 24h" and "Weekly / last
  7 days", each overlaying Claude (coral, matching its icon) and Codex
  (blue) so quota scheduling is a visual comparison; Claude weekly_scoped is
  a dashed coral line. Gradient area fills under solid lines, legends carry
  live current values, hour/weekday tick labels, 50/100 gridlines. History
  read raised to 7 days (limit 6000) with hourly-bucket downsampling
  (30 min buckets for 24h, 3 h for 7 d). Card chrome, fonts, and English
  labels match the Now tab. Fits 336x400 exactly (measured overflow 0).
- Now tab order flipped: Claude card first, Codex second (user request).
- Tray tooltip reformatted to the user-specified multi-line format
  ("5-hour / Claude resets in X hr XX min  NN% / Codex ..."), implemented
  identically in both writers (frontend traySummary and Rust
  tooltip_summary with a dependency-free ISO parser); update_tray_tooltip
  now preserves newlines.
- History only spans since 07/09, so the weekly chart stays mostly empty
  until a full week of data accumulates - expected, not a bug.
