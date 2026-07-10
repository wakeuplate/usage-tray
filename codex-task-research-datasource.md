# Task: Research alternative Claude usage data sources (read-only investigation, no code changes to limit-lens)

## Context

We are planning `limit-lens`, a Windows tray app that shows Claude + Codex usage (5h/weekly %, reset time). The current PLAN.md's Claude "safe mode" relies on a Claude Code statusLine collector — but this has two serious problems:

- The VS Code extension never executes statusLine commands (confirmed: https://github.com/anthropics/claude-code/issues/23994).
- Even in CLI mode, statusLine only updates while Claude Code is actively running, so data goes stale the moment the terminal is closed.

We found a promising alternative: `sr-kai/claudeusagewin` reportedly reads `~/.claude/.credentials.json` (the OAuth token Claude Code already stores locally after login) directly, instead of depending on statusLine. If this works, it would let us query Claude usage on demand, at any time, regardless of CLI vs extension — solving both problems above.

## What to investigate (read-only — clone or browse via `gh`/`git`, do not modify anything in `D:\claude-projects`)

1. **`sr-kai/claudeusagewin`** (https://github.com/sr-kai/claudeusagewin)
   - Find the exact code that reads `~/.claude/.credentials.json`.
   - What field(s) does it extract from that file (access token? refresh token? org id?)?
   - What API endpoint(s) does it call with that token, and what does the response contain — specifically, can it get 5h/weekly usage percentage and reset time, or only account/session metadata?
   - Does it call any official/documented Anthropic API, or an undocumented one used internally by Claude Code?

2. **Risk comparison: this OAuth token vs. the `sessionKey` cookie approach (used by QuotaGem, already risk-assessed in our PLAN.md)**
   - What is this token's expiry/refresh behavior?
   - What scope/permissions does it grant — read-only usage info, or can it be used to act on the account (send messages, change settings, etc.)?
   - Is it the same credential Claude Code itself uses for normal operation (i.e., no *new* attack surface is created by reading it), or a separately-obtained secret?

3. **`Finesssee/Win-CodexBar`** (https://github.com/Finesssee/Win-CodexBar)
   - It claims to show Codex + Claude usage "without having to login." Find out what this actually means — does it also read a locally-stored credential/token file rather than prompting a fresh login? Which files does it read for Claude and for Codex respectively?

4. **Bonus, only if time permits — combined tools' approach:**
   - `nek0der/CodexBarWin` and `babakarto/CodexBar-Win` — briefly check what Claude data source each uses (statusLine? credentials.json? sessionKey?). One paragraph each is enough.

## Output

Write your findings to `D:\claude-projects\limit-lens\RESEARCH-datasource-20260707.md` (this file, inside the limit-lens project folder, is fine to create). Structure:

- One paragraph per repo/question above.
- Cite the actual file path and line/function in the source you looked at for every factual claim (e.g. "`Services/CredentialReader.cs:42` reads the `accessToken` field").
- End with a one-paragraph recommendation: does the `.credentials.json` approach look viable as a replacement for the statusLine collector in our PLAN, and is it lower-risk than `sessionKey`?

Do not modify `PLAN.md`, `CLAUDE_REVIEW_PROMPT.md`, or any other existing file in `limit-lens`. Only create the new research file above.
