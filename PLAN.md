# UsageTray

個人用 Windows 系統匣工具，用來同時查看 Codex 與 Claude 的 5 小時、每週用量、重置時間與歷史使用情境。

## 目標

- 在 Windows 系統匣常駐。
- hover 顯示一行快速狀態。
- click 展開漂亮、清楚、接近 iOS Control Center / Raycast 的小面板。
- 同時顯示 Codex 與 Claude：5h 使用率、5h reset、weekly 使用率、weekly reset。
- 使用橫式 bar chart，不用圓餅圖。
- 支援深色、淺色、跟隨系統主題。
- 本地運行，安全優先，不預設上傳任何資料。
- 可記錄歷史，用來理解自己多久用到高水位、滿額撐多久、用了多少 token。

## 非目標

- v1 不做手機原生 app。
- v1 不以 Claude sessionKey 作為預設資料來源。
- v1 不追求 Claude web / desktop 的即時絕對精準，除非使用者明確開啟高風險模式。
- 不做團隊管理、雲端同步、帳號共享或跨裝置資料同步。

## 建議技術方案

- Desktop shell：Tauri v2。
- Backend：Rust。
- UI：React + TypeScript。
- Local DB：SQLite，放在 `%APPDATA%\UsageTray\usage-tray.sqlite`。
- Config：JSON，放在 `%APPDATA%\UsageTray\config.json`。
- Tray：Tauri tray API。
- Popup：Tauri window 或 tray-attached compact window。
- Optional web dashboard：v1 可先保留設計，不預設啟用。

## 資料來源

### 已驗證結論

- QuotaGem 的 Claude account-level usage 不是安全本機資料源。它從登入視窗取得 `sessionKey` cookie，再呼叫 `https://claude.ai/api/organizations` 與 `https://claude.ai/api/organizations/{org}/usage`。
- QuotaGem 回傳的 Claude `five_hour.utilization`、`seven_day.utilization`、`resets_at` 需要登入憑證；未發現免 `sessionKey` 的 Claude 百分比 / reset 路徑。
- QuotaGem 的 Codex 主路徑是 spawn `codex app-server`，透過 JSON-RPC 呼叫 `account/rateLimits/read`，讀 `rateLimits.primary/secondary` 的 `usedPercent`、`windowDurationMins`、`resetsAt`。這是目前最接近安全且精準的 Codex 資料源。
- `sr-kai/claudeusagewin` 顯示更好的 Claude Windows 資料源：讀取 Claude Code 已存在的 `%USERPROFILE%\.claude\.credentials.json` 或 WSL 內的 `.credentials.json`，使用 Claude Code OAuth access token 呼叫 `https://api.anthropic.com/api/oauth/usage`。它可顯示 5h / weekly percentage 與 reset countdown，且不需要瀏覽器 `sessionKey`。
- `NYCU-Chung/cc-statusline` 顯示 Claude Code 的 statusLine payload 可能包含 `rate_limits.*.used_percentage` 與 `resets_at`。它把 snapshot 寫入 `~/.claude/rate-limit-snapshots.json`，並做跨 session 聚合與 reset rollover。這代表 Claude 安全模式可以學它的方法，但必須做成最小 collector，不照搬整套 hooks。

### Codex

優先順序：

1. 本機 `codex app-server` rate limit 資訊。
2. `~/.codex/sessions/**/*.jsonl`。
3. `~/.codex/logs_2.sqlite` 或其他 Codex 本機 SQLite log。

Codex 讀取原則：

- 只讀本機檔案或本機 app server。
- 不送 prompt，不呼叫模型，不消耗 token。
- 不上傳任何 log。
- 解析錯誤時顯示資料來源失效，而不是靜默顯示舊資料。

### Claude 安全模式

優先順序：

1. Claude Code OAuth usage collector：唯讀尋找 `%USERPROFILE%\.claude\.credentials.json` 與 WSL `.credentials.json`，用 access token 查 `https://api.anthropic.com/api/oauth/usage`。
2. UsageTray 最小 statusLine collector 產出的 Claude Code rate-limit snapshot。
3. `NYCU-Chung/cc-statusline` 相容資料：`~/.claude/rate-limit-snapshots.json`，若使用者已安裝，可唯讀匯入。
4. ccusage 可讀到的 Claude Code token / cost 歷史資料。
5. 若無 Claude Code 資料，顯示 unavailable，並提示可設定安全模式資料源。

Claude 安全模式限制：

- 能安全讀到的是 Claude Code 相關資料。
- Claude web / desktop 可能與 Claude Code 共用訂閱用量池，但沒有安全的本機官方用量 API。
- 不讀 sessionKey 時，web / desktop 的用量變化可能無法即時反映，只能等 Claude Code 端資料更新或間接推估。
- 不讀 sessionKey 時，Claude 安全模式優先顯示 `Claude Code OAuth usage`。這比 statusLine 更適合常駐 tray，因為它可按需查詢，不依賴 Claude Code CLI 目前是否開著。
- OAuth usage API 是 Claude Code 內部 / 未公開 API，可能變動；UI 需標示資料來源與 freshness。
- 若 statusLine payload 沒有 rate limit 欄位，UI 退回 token trend、cost estimate、最近活躍時間，並把任何推估值標示為 estimated。

### Claude Code OAuth usage collector

這是 v1 的 Claude 安全模式主路徑，比 `sessionKey` 更適合作為預設，因為它重用 Claude Code 已經存在的本機 OAuth credential，不需要把瀏覽器 cookie 搬到工具內。

Collector 行為：

- 搜尋 Windows native credential：`%USERPROFILE%\.claude\.credentials.json`。
- 搜尋 WSL credential：`\\wsl$\<distro>\home\<user>\.claude\.credentials.json` 與 `\\wsl.localhost\<distro>\home\<user>\.claude\.credentials.json`。
- 若多個 credential 存在，選最近 modified 的檔案，讓它跟隨使用者最近使用的 Claude Code installation。
- 從 credential 讀取 access token；不複製 token 到 UsageTray config、SQLite、log 或 export。
- 呼叫 `https://api.anthropic.com/api/oauth/usage`。
- Request header 使用 Claude Code 相容格式：`Authorization: Bearer <token>`、`User-Agent: claude-code/<version>`、`anthropic-beta: oauth-2025-04-20`。
- 若 access token 過期，2026-07-10 已依使用者需求改為自動刷新 refresh token，並在通過競態檢查後原子寫回 `.credentials.json`；若刷新或寫回失敗再回報可操作錯誤。舊政策僅供歷史：v1 原本預設不自動刷新，先提示使用者重新登入 Claude Code。
- 回傳資料若包含 5h / weekly percentage 與 reset time，Claude card 可顯示完整 bar 與 countdown。

安全邊界：

- OAuth access token 仍是 bearer credential，不是公開資料。
- 風險低於瀏覽器 `sessionKey` 的增量風險，因為這是 Claude Code 本來就存在的 credential；但任何能讀取 token 的程式仍可能呼叫相容的 Claude Code OAuth endpoint。
- UsageTray 不應持久保存 token；每次查詢時從原始 credential 讀取，使用後只保留聚合 usage 結果。
- 2026-07-10 已由使用者需求取代：collector 會自動刷新並原子寫回 `.credentials.json`；舊政策僅供歷史記錄，不再視為現況。

### Claude Code 最小 statusLine collector

這是 Claude OAuth usage collector 失效時的 fallback，不是 v1 主路徑。UsageTray 不照搬 `cc-statusline` 整套 dashboard，只學三個資料處理方法：rate-limit snapshot、reset rollover、delta-based token/cost 累積。

Collector 原則：

- 單一 statusLine command，預設 refreshInterval 30 秒。
- 只讀 Claude Code 傳入的 statusLine payload。
- 只寫聚合後 snapshot，不寫 prompt、message history、edited files、subagent、MCP 狀態。
- 不做 session summary，不呼叫 Claude 重寫摘要，不消耗模型用量。
- 不安裝 `UserPromptSubmit`、`Stop`、`PostToolUse` 等額外 hooks，除非後續明確需要 token delta 精準化。
- 輸出到 `%APPDATA%\UsageTray\claude-code-snapshots.jsonl` 或 SQLite，不寫入 `.claude` 持久狀態；若必須接入 Claude Code statusLine，才以 opt-in 方式修改 `C:\Users\user\.claude\settings.json`。

Collector 需要擷取的欄位：

- timestamp。
- session id 或 transcript filename hash。
- model。
- 5h used percentage。
- 5h resets_at。
- 7d used percentage。
- 7d resets_at。
- token counts。
- cost total。
- source freshness。

Reset rollover：

- 若 `resets_at` 已過期，UI 不沿用舊 percent。
- 5h 視窗過期後顯示 0% 或 `waiting for next Claude Code update`，並標示資料來自 rollover。
- 7d 視窗同理。
- rollover 只影響顯示，不改寫原始 snapshot。

跨 session 聚合：

- 同一 agent / window 取最新可用 snapshot。
- 若多個 Claude Code session 都有 snapshot，取 `resets_at` 最晚且 captured_at 最新的一組，並保留 peak percent 作為 history。
- 對 UI 顯示標籤使用 `Claude Code observed`，避免誤導為 Claude account 全域精準值。

### Claude 精準模式

Claude 精準模式是可選、高風險模式，不列入 v1 預設。

- 資料源：`claude.ai/api/organizations/{org}/usage`。
- 必要憑證：Claude `sessionKey` 與 organization id。
- 可取得：5h utilization、5h reset、7d utilization、7d reset。
- UI 必須顯示 `Precision mode` 與風險狀態。
- 沒有啟用精準模式時，Claude card 不顯示假裝精準的百分比 bar。
- 若同時有 OAuth 安全模式與 Precision Mode，UI 預設以 OAuth 安全模式為主，除非使用者明確指定 account-level Precision Mode。

## Claude sessionKey 風險評估

### 結論

`sessionKey` 不應作為 v1 預設資料來源。它可以作為進階、高風險、明確 opt-in 的精準模式，但必須隔離設計。

### 優點

- 最可能取得 Claude web / desktop / Claude Code 共用額度的即時狀態。
- 精準度高於只讀 Claude Code statusLine。
- UI 可以更接近 QuotaGem 類工具，直接顯示 account-level usage。

### 風險

- `sessionKey` 類似登入憑證，不是一般設定值。
- 若明文存在本機 config，惡意程式、同步備份、除錯 log、截圖、誤分享檔案都可能外洩。
- 外洩後可能被冒用 Claude web session，在該 session 權限內讀帳號狀態、消耗額度或操作帳號。
- Claude 可能改 API 或風控策略，導致工具失效、session 被撤銷或觸發異常登入。
- 一旦工具保存 `sessionKey`，安全定位會從「本機 log viewer」升級成「保存登入憑證的工具」。

### 是否可承受

- 公司電腦、多人共用電腦、常裝不明軟體、會同步 `%APPDATA%`、帳號內有重要資料：不可承受。
- 個人電腦、有磁碟加密、不跑不明軟體、不同步 config、可接受 session 被撤銷：勉強可承受。
- 本專案使用者情境是個人電腦但含敏感個資：評估為中高風險，不適合作為預設。

### 若未來加入 sessionKey 模式，最低要求

- 必須是 Advanced / Precision Mode，預設關閉。
- 必須明確告知風險。
- 不得明文存檔。
- 優先存 Windows Credential Manager 或 DPAPI 加密後的 Windows 使用者範圍 secret。
- 不得寫入 log、crash report、history DB 或 export。
- 提供一鍵刪除 credential。
- 啟用後 UI 必須顯示目前為 high-risk precision mode。

## 更新頻率與 token 成本

本工具不應消耗 AI token。原因：資料來源是本機檔案、本機 SQLite、或本機 app-server 狀態，不送 prompt 給模型。

建議更新頻率：

- UI countdown：每 1 秒更新，只更新畫面時間，不重讀資料。
- Codex source refresh：每 30 秒。
- Claude OAuth usage collector：預設 2 分鐘一次，手動 refresh 可立即查；連續失敗退避到 5 / 10 / 30 分鐘。
- Claude statusLine collector fallback：由 Claude Code statusLine refreshInterval 30 秒觸發。
- Claude Precision Mode usage endpoint：預設 2 分鐘一次，手動 refresh 可立即查；連續失敗退避到 5 / 10 / 30 分鐘。
- Manual refresh：使用者可點擊立即刷新。
- History snapshot：每 60 秒寫入一次，只有數值變化或 reset boundary 變化時才寫。
- Error backoff：資料來源連續失敗時退避到 2 分鐘，避免背景噪音。

## 歷史追蹤

### 記錄內容

SQLite 表建議：

- `usage_snapshots`
  - `id`
  - `captured_at`
  - `agent`：`claude` / `codex`
  - `window`：`5h` / `weekly`
  - `percent_used`
  - `reset_at`
  - `tokens_total`
  - `tokens_delta`
  - `estimated_cost`
  - `source`
  - `source_freshness_seconds`

- `limit_cycles`
  - `id`
  - `agent`
  - `window`
  - `cycle_start_at`
  - `cycle_reset_at`
  - `first_seen_at`
  - `peak_percent`
  - `peak_reached_at`
  - `first_80_at`
  - `first_95_at`
  - `first_100_at`
  - `time_above_80_seconds`
  - `time_at_or_above_100_seconds`
  - `tokens_total`
  - `estimated_cost_total`

若 reset time 不可得，`limit_cycles` 必須標示為 approximate cycle。安全模式下的 Claude 歷史追蹤以 continuous snapshots 與 token trend 為主，不強行切精準 5h cycle。

### 資料來源對應

- Claude token / cost：OAuth usage API、ccusage 或 Claude Code 本機 usage 資料。
- Claude percent / reset：OAuth usage collector 為主；statusLine snapshot 為 fallback；Precision Mode 可顯示 Claude web account-level quota。
- Codex percent / reset：`codex app-server account/rateLimits/read` 為主，JSONL rate limit payload 為 fallback。
- Codex token / cost：Codex JSONL / SQLite log 聚合，cost 依本機 rate table 估算。
- Pricing rate table：內建版本化 JSON，允許手動更新；任何 cost 都顯示為 estimate。

### 呈現方式

主 popup 只放即時資訊，避免擁擠。

History view 顯示：

- 今日用量：Claude / Codex token、cost、最高使用率。
- 本輪 5h：Codex 與 Claude OAuth collector 顯示 quota；statusLine fallback 顯示 Claude Code observed quota；若無 rate-limit snapshot 則退回 token burn trend。
- Weekly：7 天熱力圖與每日累積。
- Mini trend：每個 agent 一條小型折線或水平 timeline。
- Reset log：最近幾次 reset 前的 peak 與 token。

## UI / UX 設計系統

### 設計方向

- 風格：iOS Control Center + Raycast。
- 目標：安靜、精準、漂亮、資訊密度高。
- 避免：圓餅圖、過度漸層、紫色 AI 風、卡片套卡片、巨大 landing page 感。

### Tray icon

不用電池 icon。

建議使用「雙軌膠囊」：

- 上軌代表 Claude，暖橘。
- 下軌代表 Codex，青藍。
- 填滿比例代表 5h 使用率。
- 外框代表 weekly 壓力，可用細邊或角落小點表示。
- 80% 以上轉 warning amber。
- 95% 以上轉 danger red。
- 若資料不可用，改為灰色斜線或中性缺口。

### Hover tooltip

格式：

`Claude 38% · reset 3h05m | Codex 72% · reset 1h20m`

若資料不完整：

`Claude unavailable | Codex 72% · reset 1h20m`

### Popup layout

預設大小：約 `380 x 460`。

區塊：

1. Header
   - 左：`UsageTray`
   - 右：Theme toggle、Refresh、Settings icon。
   - 副標：整體狀態一句話，例如 `Codex is the current bottleneck`。

2. Agent cards
   - Claude card。
   - Codex card。
   - 每張卡固定包含：
     - agent name。
     - source freshness。
     - 5h horizontal bar。
     - 5h reset countdown。
     - weekly horizontal bar。
     - weekly reset countdown。
     - token burn rate。
   - Claude 安全模式若沒有 percent / reset，改顯示 token trend card，不顯示誤導性的 quota bar。
   - Claude OAuth collector 顯示 `Claude Code OAuth` 標籤。
   - Claude statusLine fallback 顯示 `Observed via Claude Code` 標籤。

3. Footer strip
   - `History`
   - `Sources`
   - `Settings`

### Typography

不外連字型，避免隱私與啟動延遲。

- Primary：`Segoe UI Variable`。
- Fallback：`Segoe UI`, `system-ui`, `sans-serif`。
- Numeric：`Segoe UI Variable` with `font-variant-numeric: tabular-nums`。
- 字重：
  - Header：600。
  - Card title：600。
  - Main percentage：650 或 700。
  - Labels：500。
  - Muted metadata：400。

### Color tokens

Dark theme：

- `bg`: `#0B0D10`
- `panel`: `#171A20`
- `surface`: `#20242C`
- `surfaceElevated`: `#262B34`
- `text`: `#F5F7FA`
- `muted`: `#9AA3AF`
- `border`: `rgba(255,255,255,0.10)`

Light theme：

- `bg`: `#F5F7FA`
- `panel`: `#FFFFFF`
- `surface`: `#EEF1F5`
- `surfaceElevated`: `#FFFFFF`
- `text`: `#111827`
- `muted`: `#64748B`
- `border`: `rgba(15,23,42,0.10)`

Accent：

- Claude：`#D97745`
- Codex：`#35A7D6`
- Warning：`#F59E0B`
- Danger：`#EF4444`
- Success：`#22C55E`

### Bar chart rules

- 0–50%：agent brand color。
- 50–80%：agent brand color mixed with warning。
- 80–95%：warning。
- 95–100%：danger。
- 超過或滿額：danger bar + subtle pulse，但尊重 `prefers-reduced-motion`。
- Bar 必須保留文字外部標籤，不把文字壓在 bar 內。

### Theme behavior

- `System`：跟隨 Windows theme。
- `Light`：強制淺色。
- `Dark`：強制深色。
- 切換偏好只存在 config，不需要帳號同步。

## 安全與隱私原則

- 預設完全本機運行。
- 預設不開任何 LAN port。
- 預設不傳送 telemetry。
- 預設不讀 browser cookie、不讀 Claude sessionKey。
- 預設可讀 Claude Code `.credentials.json`，但只在使用者啟用 Claude OAuth collector 後讀取，且不複製 credential。
- 不寫入 prompt 原文。
- 不儲存完整 Codex / Claude 對話內容，只儲存聚合後 usage 數字。
- 若 parser 必須掃描 JSONL，只取 token、rate limit、timestamp、model、thread id hash。
- 最小 statusLine collector 不保存 message history、summary、edited files、subagent、MCP 狀態。
- thread id 或 project path 如需保存，應 hash 或可關閉。
- export 功能若加入，預設只匯出聚合數字。

## 手機方案

v1 不做手機原生版。

可選 v1.5：

- Local web dashboard，預設只 listen `127.0.0.1`。
- 若使用者明確啟用 mobile mode，才允許綁定 LAN IP。
- 手機首次連線必須輸入桌面端顯示的 PIN。
- UI 顯示風險提示：同網路裝置可能可嘗試連線。
- 建議搭配 Tailscale 或 Windows 防火牆白名單。
- 手機模式不暴露 raw logs，只暴露聚合後 JSON。

## Settings

Settings page 至少包含：

- Theme：System / Light / Dark。
- Refresh interval：15 秒、30 秒、60 秒、自訂。
- Auto-start：開機自啟開關，使用 Tauri autostart plugin 或 Windows Run key。
- Data sources：Codex executable path、Codex logs path、Claude local usage path。
- Claude OAuth credentials：Windows native / WSL / disabled。
- Claude Code collector：未設定 / 已設定 / 匯入 cc-statusline snapshots。
- History retention：30 / 90 / 365 天。
- Privacy：是否儲存 project path hash、是否啟用 export。
- Mobile dashboard：關閉 / localhost only / LAN with PIN。
- Claude Precision Mode：預設關閉，啟用前顯示 sessionKey 風險與 Credential Manager / DPAPI 儲存策略。

## Update Check

- v1 不做自動更新。
- 可選擇在啟動時檢查 GitHub releases。
- 檢查更新不得上傳本機 usage 資料。
- 若檢查失敗，靜默降級，不影響 tray app。

## Spike Tasks

正式實作前先做三個最小驗證：

1. Codex source spike：呼叫 `codex app-server account/rateLimits/read`，確認 Windows 上可取得 `usedPercent` 與 `resetsAt`。
2. Claude OAuth spike：唯讀解析 `.claude\.credentials.json`，呼叫 OAuth usage endpoint，確認 response 是否含 5h / 7d percent 與 reset。
3. Tray popup spike：測試 Windows 125%、150% DPI、多螢幕下的 tray popup 位置與尺寸。
4. Claude statusLine fallback spike：用最小 statusLine collector 驗證 Claude Code payload 是否含 5h / 7d `used_percentage` 與 `resets_at`。
5. cc-statusline compatibility spike：若使用者已安裝 cc-statusline，唯讀解析 `~/.claude/rate-limit-snapshots.json`，確認能否匯入。

## 開發驗收標準

- Windows tray icon 可常駐。
- hover tooltip 正常顯示一行快速狀態。
- click popup 顯示 Codex 的 5h 與 weekly bar；Claude 安全模式優先顯示 OAuth usage 5h / weekly bar，fallback 顯示 Claude Code observed bar，缺資料時退回 token trend；Claude Precision Mode 顯示 web sessionKey account-level bar。
- reset countdown 隨時間更新。
- 深色、淺色、跟隨系統可切換。
- 沒有 Claude sessionKey 也能以安全模式運作，顯示 Claude OAuth usage、Claude Code observed quota 或 token trend，但不得誇大資料來源。
- 資料不可用時有清楚 fallback UI。
- SQLite history 可正確記錄 snapshot 與 cycle。
- 不外連、不 telemetry、不儲存敏感憑證。
- UI 在 125%、150% Windows scaling 下不破版。

## 參考專案

- `gyozalab/QuotaGem`：UI 與 Claude account usage 精準度可參考，但 sessionKey 風險不可作為預設。
- `sr-kai/claudeusagewin`：Claude Code OAuth `.credentials.json` 方案最值得採用為 v1 Claude 主資料源；需注意它使用 undocumented API。
- `f-is-h/usage4claude`：macOS menu bar 與 Keychain 安全模型可參考，但不能直接用於 Windows。
- `aqua5230/usage` 與 Windows fork：本機資料源與 Claude Code / Codex 同屏方向可參考，但 UI 需重做。
- `ccusage`：可作為 Claude token / cost 歷史資料參考，不適合單獨當即時 tray UI。
- `NYCU-Chung/cc-statusline`：Claude Code statusLine rate-limit snapshot、reset rollover、delta-based 累積方法值得學；不照搬 summary、message history、edited files、subagent、MCP 等重型 hooks。

## 自檢

## 目前進度（2026-07-10 +08:00）

- Codex collector：可用，主資料源為 `codex app-server account/rateLimits/read`。
- Claude collector：可用，主資料源為 Claude Code OAuth `.credentials.json` + OAuth usage API。
- Windows native build：可用，已安裝 MSVC 與 Windows SDK，`npm run tauri:dev` 已能編譯並啟動 `usage-tray.exe`。
- Tray app：已具備 popup、tooltip、背景收集、單例、history 寫入等核心行為。
- UI：已符合目前 v1 的 iOS Control Center / Raycast 方向。
- Popup layout v2：改為固定尺寸 shell，`Now / 24h / Alerts` 同尺寸；視窗為 `336x400`（372 會裁掉 Claude Scoped 列，2026-07-10 修正）；內容改為內部 overflow，而不是整窗變高。

剛完成的關鍵修正：

- `app/src-tauri/Cargo.toml` 已補上 Tauri 的 `image-png` feature，讓 tray icon 可在目前 Tauri 版本下編譯。
- Claude Code 已重新登入，Claude live usage 再次可讀。

接下來優先順序：

1. Windows 實機細節驗證：固定尺寸 popup、貼底位置、overflow、tray icon 可辨識度。
2. Telegram 通知：安全保存 bot token、取得 chat id、送 test message。
3. Threshold alerts：70% / 85% / 95% 單次提醒，避免重複洗版。
4. Auth / source alerts：Claude 或 Codex 失效時主動通知。

符合原始需求：

- Windows 可用：是。
- 系統匣常駐：是。
- hover 一行小字：是。
- click 展開詳細狀態：是。
- 同時看 Codex 與 Claude：是。
- 5h / weekly / reset：是。
- 橫式 bar chart：是。
- iOS 風格 UI：是。
- 深淺色：是。
- 安全：預設安全，不讀 sessionKey。
- 精準：Codex 較精準；Claude 安全模式以 Claude Code OAuth usage 為主；sessionKey Precision Mode 作為最後 fallback 或明確需求。
- 歷史追蹤：有設計。
- 手機：保留 optional local web dashboard，不列入 v1 核心。

主要風險：

- Claude web / desktop usage 即時精準度不足。
- Claude OAuth usage API 是 undocumented，可能變動或被風控限制。
- Claude Code statusLine payload 欄位需實測；若 Anthropic 改 payload，安全模式可能退回 token trend。
- Codex log 格式或 app-server API 可能變動。
- Claude statusLine hook 需要修改 `.claude/settings.json`，必須 opt-in。
- Tauri tray popup 在 Windows 多螢幕與 DPI scaling 需實測。
- 若使用者要求 Claude web / desktop 共用額度即時精準，必須啟用高風險 Precision Mode。

建議：

- v1 以 Claude Code OAuth usage collector + Codex app-server 做主要資料源。
- v1.1 再做手機 local dashboard。
- v1.2 才評估 sessionKey precision mode，且必須通過安全審查；若 OAuth usage 已足夠，sessionKey 可不做。
