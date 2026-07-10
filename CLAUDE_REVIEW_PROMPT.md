# Claude Review Prompt

你現在要審查一個 side project 規劃，不要執行任何修改。

限制：

- 你只能規劃與審查。
- 不得建立、修改、刪除任何檔案。
- 不得安裝套件。
- 不得執行 build、test、lint、format。
- 不得修改 `C:\Users\user\.claude\` 或 `D:\claude-projects\` 任何檔案。
- 若需要查資料，先說明需要查什麼與原因，不要直接上網。
- 為了省用量，先只讀 `PLAN.md`，不要遞迴掃描整個資料夾。

工作目標：

請進入此專案資料夾：

`D:\claude-projects\limit-lens`

讀取：

`PLAN.md`

請審查這份方案是否合格，重點是：

1. 是否真的符合「Windows 系統匣工具，同時看 Codex 與 Claude 用量」的需求。
2. 安全設計是否足夠，尤其是 Claude sessionKey 的風險處理是否合理。
3. 資料來源是否可行，尤其是新增的「Claude Code OAuth usage collector」是否適合取代 statusLine 成為 v1 Claude 主資料源。
4. 更新頻率是否合理，是否會消耗 AI token 或造成明顯系統負擔。
5. UI / UX 設計是否足夠具體，能否交給工程師直接實作。
6. 歷史追蹤設計是否能回答「多久用到高水位、滿額撐多久、用了多少 token」。
7. 手機方案是否合理，是否有隱私風險。
8. 是否有遺漏的重要測試、風險、替代方案。
9. 是否正確區分 `Claude OAuth usage`、`Claude Code observed quota`、`Claude web sessionKey precision mode`，避免誤導使用者。
10. 是否避免照搬 cc-statusline 的重型 hooks，例如 summary、message history、edited files、subagent、MCP 狀態。
11. OAuth `.credentials.json` 方案是否有明確安全邊界：不複製 token、不寫 log、不寫 DB、不自動 refresh token，除非另做風險審查。

輸出格式：

- 先給一句結論：`合格`、`大致合格但需修改`、或 `不合格`。
- 接著列出最多 10 個問題，依嚴重度排序。
- 每個問題包含：問題、原因、建議修改。
- 最後給一段「建議修訂方向」，不要直接改檔。

再次提醒：你只能審查，不得執行或修改。
