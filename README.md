# UsageTray

一個 Windows 系統匣小工具，一眼看完 **Codex** 與 **Claude Code** 的額度用量、重置時間與近 24 小時走勢，額度快用完時透過 **Telegram** 主動提醒。

本機執行、資料不出門：用量數字直接讀自本機的 Codex app-server 與 Claude Code 登入憑證，不經過任何第三方伺服器。

## 功能

- **系統匣常駐**：左鍵點圖示彈出面板，顯示 Codex／Claude 的 5 小時與每週額度、已用百分比、重置時間。
- **三個分頁**：`Now`（即時用量）、`24h`（近 24 小時峰值走勢）、`Alerts`（Telegram 警報設定）。
- **Telegram 警報**：用量跨過 50%／85%／95% 門檻時推播通知，附文字版用量長條圖報表；同一額度週期不重複轟炸。
- **Claude token 自動刷新**：Claude Code 的 OAuth token 每 8 小時過期，UsageTray 會自動用 refresh token 換新並寫回，不用手動重新登入。
- **開機自動啟動**：安裝後第一次執行即自動註冊。

## 系統需求

- Windows 10/11（x64）
- [Python 3.10+](https://www.python.org/downloads/)，且 `python` 在 PATH 中（收集器為 Python 腳本，全部使用標準函式庫，無需 pip 安裝任何套件）
- 至少安裝並登入其中一個：
  - [Codex CLI](https://github.com/openai/codex)（讀取 `codex app-server` 的額度資料）
  - [Claude Code](https://code.claude.com/docs/en/overview)（讀取 OAuth 憑證查詢額度）

## 安裝

1. 執行 `release/UsageTray_0.1.0_x64-setup.exe`（或自行建置，見下）。
2. 從開始選單啟動 UsageTray，系統匣會出現圖示；之後開機自動啟動。

### Telegram 警報設定（選用）

1. 跟 [@BotFather](https://t.me/BotFather) 建一個 bot，取得 bot token。
2. 對你的 bot 傳一則任意訊息。
3. 開 UsageTray 的 `Alerts` 分頁，貼上 token，按偵測即可自動找到你的 chat。
4. Token 以 Windows DPAPI 加密存於 `%APPDATA%\UsageTray\`，不會以明文落地。

## 從原始碼建置

需要 Rust（MSVC toolchain）、Node.js、Visual Studio C++ Build Tools 與 Windows SDK。詳細步驟見 [docs/WINDOWS-BUILD.md](docs/WINDOWS-BUILD.md)。

```powershell
cd app
npm install
npm run tauri build
# 產出：app/src-tauri/target/release/bundle/nsis/UsageTray_<版本>_x64-setup.exe
```

## 架構

- **外殼**：Tauri v2（Rust）＋ React/TypeScript 前端，視窗約 336×400，無邊框貼齊系統匣。
- **收集器**：`collectors/collect_usage_tray.py` 讀取兩個資料來源並輸出淨化後的 JSON（詳見 [docs/COLLECTOR-CONTRACT.md](docs/COLLECTOR-CONTRACT.md)）：
  - Codex：本機 `codex app-server` 的 `account/rateLimits/read` JSON-RPC。
  - Claude：`%USERPROFILE%\.claude\.credentials.json` 的 OAuth token 呼叫官方 usage API；過期時自動 refresh 並原子寫回（含競態防護與 10 分鐘失敗冷卻）。
- **歷史**：`collectors/history_snapshot.py` 將快照寫入 `%APPDATA%\UsageTray\snapshots.jsonl`（見 [docs/SNAPSHOT-HISTORY.md](docs/SNAPSHOT-HISTORY.md)）。
- **警報**：`collectors/telegram_bridge.py` 處理門檻判斷、去重與 Telegram 推播。

## 安全邊界

- 任何 token、cookie、session key 永不寫入 log、輸出或設定檔。
- 收集器輸出只含聚合後的百分比與時間，錯誤訊息會先移除敏感字串。
- 對 `.credentials.json` 的寫回僅限 token 刷新，原子寫入且保留其他欄位。

## 測試

```powershell
python collectors/test_collect_usage_tray_contract.py
```
