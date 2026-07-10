import React from "react";
import ReactDOM from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";
import "./styles.css";

type UsageWindow = {
  name: string;
  used_percent: number | null;
  remaining_percent: number | null;
  reset_at: string | null;
  reset_at_unix: number | null;
  window_duration_mins: number | null;
};

type AgentResult = {
  available: boolean;
  source: string;
  captured_at?: string;
  error: { code: string; message?: string } | null;
  diagnostics?: Record<string, unknown>;
  windows: Record<string, UsageWindow>;
};

type CollectorSnapshot = {
  schema_version: string;
  captured_at: string;
  agents: Record<string, AgentResult>;
};

type HistorySnapshot = CollectorSnapshot & {
  collector_schema_version?: string;
};

type AlertSettings = {
  enabled: boolean;
  chat_id: string | null;
  chat_label: string | null;
  has_token: boolean;
  thresholds: number[];
};

type ViewMode = "usage" | "history" | "alerts";

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  hour12: true
});

const weekdayResetFormatter = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
  hour12: true
});

function clampPercent(value: number | null | undefined): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${Math.round(value)}%`;
}

function formatMonthDay(date: Date): string {
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
}

function shortWeekday(date: Date): string {
  return new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(date);
}

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function formatCaptured(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return `${formatMonthDay(date)} ${timeFormatter.format(date)}`;
}

function formatReset(value: string | null | undefined, kind: string): string {
  if (!value) return "No reset";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No reset";

  const today = startOfLocalDay(new Date());
  const target = startOfLocalDay(date);
  const dayDelta = Math.round((target - today) / 86_400_000);
  const time = timeFormatter.format(date);

  if (kind === "weekly" || kind === "weekly_scoped") {
    return `${formatMonthDay(date)} ${shortWeekday(date)} ${time}`;
  }
  if (dayDelta === 0) return time;
  if (dayDelta === 1) return `tomorrow ${time}`;
  return weekdayResetFormatter.format(date);
}

function pickLabel(key: string): string {
  if (key === "five_hour") return "5-hour";
  if (key === "weekly") return "Weekly";
  if (key === "weekly_scoped") return "Scoped";
  return key.replaceAll("_", " ");
}

function friendlyError(code: string | undefined): string {
  if (code === "claude_auth_expired" || code === "claude_credentials_not_found") {
    return "Sign in to Claude Code";
  }
  if (code === "codex_command_not_found") return "Codex is not installed";
  return "Data unavailable";
}

function getContextWindow(agent?: AgentResult): string | null {
  const context = agent?.diagnostics?.context_window;
  if (!context || typeof context !== "object") return null;

  const data = context as { used_tokens?: unknown; total_tokens?: unknown };
  if (typeof data.used_tokens !== "number" || typeof data.total_tokens !== "number") return null;

  if (data.total_tokens <= 0) return null;
  const remaining = 100 - (data.used_tokens / data.total_tokens) * 100;
  return formatPercent(clampPercent(remaining));
}

function traySummary(snapshot: CollectorSnapshot): string {
  const codex = formatPercent(snapshot.agents.codex?.windows.five_hour?.remaining_percent);
  const claude = formatPercent(snapshot.agents.claude?.windows.five_hour?.remaining_percent);
  return `Codex 剩餘 ${codex} | Claude 剩餘 ${claude}`;
}

function withTimeout<T>(promise: Promise<T>, milliseconds: number, message: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), milliseconds);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function AgentIcon({ name }: { name: string }) {
  return <span className={`agent-icon ${name}`} aria-hidden="true" />;
}

function WindowRow({ label, window, kind }: { label: string; window?: UsageWindow; kind: string }) {
  const used = clampPercent(window?.used_percent);
  const high = used >= 90;
  const warm = used >= 70 && used < 90;

  return (
    <div className="window-row">
      <div className="window-meta">
        <span>{label}</span>
        <span className="window-values">
          <em>{formatReset(window?.reset_at, kind)}</em>
          <strong>{formatPercent(window?.used_percent)}</strong>
        </span>
      </div>
      <div
        className="bar-shell"
        role="progressbar"
        aria-label={`${label} usage`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={window?.used_percent ?? undefined}
        aria-valuetext={formatPercent(window?.used_percent)}
      >
        <div className={`bar-fill ${high ? "danger" : warm ? "warm" : ""}`} style={{ width: `${used}%` }} />
      </div>
    </div>
  );
}

function AgentPanel({ name, agent }: { name: string; agent?: AgentResult }) {
  const windows = agent?.windows ?? {};
  const order = (name === "claude" ? ["five_hour", "weekly", "weekly_scoped"] : ["five_hour", "weekly"])
    .filter((key) => windows[key]);
  const contextWindow = name === "codex" ? getContextWindow(agent) : null;

  return (
    <section className="agent-panel">
      <div className="agent-heading">
        <div className="agent-title">
          <AgentIcon name={name} />
          <h2>{name === "codex" ? "Codex" : "Claude"}</h2>
          {name === "codex" ? <span className="context-chip">Context 剩餘 {contextWindow ?? "--"}</span> : null}
        </div>
        <span className={`status-dot ${agent?.available ? "ok" : "bad"}`}>
          {agent?.available ? "Live" : "Off"}
        </span>
      </div>

      {agent?.available ? (
        <div className="window-stack">
          {order.map((key) => (
            <WindowRow key={key} label={pickLabel(key)} window={windows[key]} kind={key} />
          ))}
        </div>
      ) : (
        <div className="empty-state">{friendlyError(agent?.error?.code)}</div>
      )}
    </section>
  );
}

function peakUsage(history: HistorySnapshot[], agentName: string, windowName: string): number | null {
  const values = history
    .map((snapshot) => snapshot.agents[agentName]?.windows[windowName]?.used_percent)
    .filter((value): value is number => typeof value === "number" && !Number.isNaN(value));
  return values.length > 0 ? Math.max(...values) : null;
}

function HistoryRow({ label, value }: { label: string; value: number | null }) {
  const used = clampPercent(value);
  const high = used >= 90;
  const warm = used >= 70 && used < 90;

  return (
    <div className="window-row">
      <div className="window-meta">
        <span>{label}</span>
        <span className="window-values">
          <em>peak</em>
          <strong>{formatPercent(value)}</strong>
        </span>
      </div>
      <div
        className="bar-shell"
        role="progressbar"
        aria-label={`${label} peak usage`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value ?? undefined}
        aria-valuetext={formatPercent(value)}
      >
        <div className={`bar-fill ${high ? "danger" : warm ? "warm" : ""}`} style={{ width: `${used}%` }} />
      </div>
    </div>
  );
}

function HistoryAgentPanel({ name, history }: { name: string; history: HistorySnapshot[] }) {
  const readings = history.filter((snapshot) => snapshot.agents[name]);
  const availableReadings = readings.filter((snapshot) => snapshot.agents[name]?.available).length;
  const order = name === "claude" ? ["five_hour", "weekly", "weekly_scoped"] : ["five_hour", "weekly"];

  return (
    <section className="agent-panel">
      <div className="agent-heading">
        <div className="agent-title">
          <AgentIcon name={name} />
          <h2>{name === "codex" ? "Codex" : "Claude"}</h2>
        </div>
        <span className="history-count">{availableReadings} readings</span>
      </div>

      {readings.length > 0 ? (
        <div className="window-stack">
          {order.map((key) => (
            <HistoryRow key={key} label={pickLabel(key)} value={peakUsage(readings, name, key)} />
          ))}
        </div>
      ) : (
        <div className="empty-state">History will appear after the first live reading.</div>
      )}
    </section>
  );
}

function AlertsPanel({
  settings,
  tokenInput,
  setTokenInput,
  onToggleEnabled,
  onSaveToken,
  onDiscoverChat,
  onSendTest,
  busy,
  busyLabel,
}: {
  settings: AlertSettings | null;
  tokenInput: string;
  setTokenInput: (value: string) => void;
  onToggleEnabled: (enabled: boolean) => void;
  onSaveToken: () => void;
  onDiscoverChat: () => void;
  onSendTest: () => void;
  busy: boolean;
  busyLabel: string | null;
}) {
  return (
    <section className="agent-panel alerts-panel">
      <div className="agent-heading">
        <div className="agent-title">
          <h2>Telegram</h2>
        </div>
        <span className={`status-dot ${settings?.enabled ? "ok" : "bad"}`}>
          {settings?.enabled ? "On" : "Off"}
        </span>
      </div>

      <div className="alerts-copy compact">
        <p>Token stays local. Press Start in Telegram, then find your chat.</p>
      </div>

      <label className="field-block">
        <span>Bot token</span>
        <input
          type="password"
          value={tokenInput}
          onChange={(event) => setTokenInput(event.target.value)}
          placeholder={settings?.has_token ? "Saved locally" : "Paste token here"}
          autoComplete="off"
          spellCheck={false}
        />
      </label>

      <div className="button-row">
        <button type="button" onClick={onSaveToken} disabled={busy || tokenInput.trim().length === 0}>
          {busyLabel === "saving" ? "Saving..." : "Save token"}
        </button>
        <button type="button" onClick={onDiscoverChat} disabled={busy || !settings?.has_token}>
          {busyLabel === "finding" ? "Finding..." : "Find my chat"}
        </button>
      </div>

      <div className="alerts-meta">
        <span>Chat</span>
        <strong>{settings?.chat_label ?? settings?.chat_id ?? "Not connected yet"}</strong>
      </div>

      <label className="toggle-row">
        <input
          type="checkbox"
          checked={settings?.enabled ?? false}
          onChange={(event) => onToggleEnabled(event.target.checked)}
          disabled={busy}
        />
        <span>Enable Telegram alerts</span>
      </label>

      <div className="alerts-copy compact">
        <p>Thresholds {settings?.thresholds?.join("% / ") ?? "50% / 85% / 95"}% · source alerts on</p>
      </div>

      <div className="button-row">
        <button type="button" onClick={onSendTest} disabled={busy || !settings?.chat_id || !settings?.has_token}>
          {busyLabel === "testing" ? "Sending..." : "Send test"}
        </button>
      </div>
    </section>
  );
}

function App() {
  const [snapshot, setSnapshot] = React.useState<CollectorSnapshot | null>(null);
  const [history, setHistory] = React.useState<HistorySnapshot[]>([]);
  const [mode, setMode] = React.useState<ViewMode>("usage");
  const [alertSettings, setAlertSettings] = React.useState<AlertSettings | null>(null);
  const [tokenInput, setTokenInput] = React.useState("");
  const [alertsBusy, setAlertsBusy] = React.useState(false);
  const [alertsBusyLabel, setAlertsBusyLabel] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const refreshing = React.useRef(false);

  const loadAlertSettings = React.useCallback(async () => {
    try {
      const response = await invoke<{ settings: AlertSettings }>("get_alert_settings");
      setAlertSettings(response.settings);
    } catch {
      setAlertSettings(null);
    }
  }, []);

  const refresh = React.useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    setLoading(true);
    setError(null);
    try {
      const data = await invoke<CollectorSnapshot>("collect_usage");
      setSnapshot(data);
      void invoke("update_tray_tooltip", { summary: traySummary(data) }).catch(() => undefined);
      try {
        setHistory(await invoke<HistorySnapshot[]>("read_history", { limit: 1_000 }));
      } catch {
        setHistory([]);
      }
    } catch (liveError) {
      try {
        const [snapshotResponse, historyResponse] = await Promise.all([
          fetch("/sample-collector-output-v0.json"),
          fetch("/sample-history-v0.json"),
        ]);
        setSnapshot((await snapshotResponse.json()) as CollectorSnapshot);
        setHistory((await historyResponse.json()) as HistorySnapshot[]);
        setError("Sample data");
      } catch {
        setError(liveError instanceof Error ? liveError.message : String(liveError));
      }
    } finally {
      refreshing.current = false;
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
    void loadAlertSettings();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [loadAlertSettings, refresh]);

  const saveAlertSettings = React.useCallback(
    async (payload: { enabled?: boolean; bot_token?: string; chat_id?: string | null; chat_label?: string | null }) => {
      setAlertsBusy(true);
      setAlertsBusyLabel(payload.bot_token ? "saving" : null);
      setError(null);
      try {
        const response = await withTimeout(
          invoke<{ settings: AlertSettings }>("save_alert_settings", {
            payload: {
              enabled: payload.enabled ?? alertSettings?.enabled ?? false,
              chat_id: payload.chat_id ?? alertSettings?.chat_id ?? null,
              chat_label: payload.chat_label ?? alertSettings?.chat_label ?? null,
              bot_token: payload.bot_token ?? null,
              clear_token: false,
            },
          }),
          8_000,
          "Telegram settings save timed out.",
        );
        setAlertSettings(response.settings);
        if (payload.bot_token) {
          setTokenInput("");
          setError("Token saved");
        }
      } catch (saveError) {
        setError(saveError instanceof Error ? saveError.message : String(saveError));
      } finally {
        setAlertsBusy(false);
        setAlertsBusyLabel(null);
      }
    },
    [alertSettings],
  );

  const discoverChat = React.useCallback(async () => {
    setAlertsBusy(true);
    setAlertsBusyLabel("finding");
    setError(null);
    try {
      const response = await withTimeout(
        invoke<{ chat_id: string; chat_label: string }>("discover_telegram_chat"),
        12_000,
        "Telegram chat lookup timed out.",
      );
      await saveAlertSettings({
        chat_id: response.chat_id,
        chat_label: response.chat_label,
      });
    } catch (discoverError) {
      setError(discoverError instanceof Error ? discoverError.message : String(discoverError));
      setAlertsBusy(false);
    }
  }, [saveAlertSettings]);

  const sendTest = React.useCallback(async () => {
    setAlertsBusy(true);
    setError(null);
    try {
      setAlertsBusyLabel("testing");
      await withTimeout(invoke("send_telegram_test"), 12_000, "Telegram test timed out.");
      setError("Telegram test sent");
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : String(testError));
    } finally {
      setAlertsBusy(false);
    }
  }, []);

  const recentHistory = React.useMemo(() => {
    const cutoff = Date.now() - 24 * 60 * 60 * 1000;
    return history.filter((item) => {
      const capturedAt = new Date(item.captured_at).getTime();
      return Number.isFinite(capturedAt) && capturedAt >= cutoff;
    });
  }, [history]);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">UsageTray</p>
          <h1>Usage</h1>
        </div>
        <div className="refresh-block">
          <span aria-live="polite">{snapshot ? formatCaptured(snapshot.captured_at) : "Waiting..."}</span>
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            {loading ? "Reading..." : "Refresh"}
          </button>
        </div>
      </header>

      <div className="mode-switch mode-switch-3" role="tablist" aria-label="Usage view">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "usage"}
          className={mode === "usage" ? "active" : ""}
          onClick={() => setMode("usage")}
        >
          Now
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "history"}
          className={mode === "history" ? "active" : ""}
          onClick={() => setMode("history")}
        >
          24h
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "alerts"}
          className={mode === "alerts" ? "active" : ""}
          onClick={() => setMode("alerts")}
        >
          Alerts
        </button>
      </div>

      {error ? <div className="notice" aria-live="polite">{error}</div> : null}

      <div className="agent-grid">
        {mode === "usage" ? (
          <>
            <AgentPanel name="codex" agent={snapshot?.agents.codex} />
            <AgentPanel name="claude" agent={snapshot?.agents.claude} />
          </>
        ) : mode === "history" ? (
          <>
            <HistoryAgentPanel name="codex" history={recentHistory} />
            <HistoryAgentPanel name="claude" history={recentHistory} />
          </>
        ) : (
          <AlertsPanel
            settings={alertSettings}
            tokenInput={tokenInput}
            setTokenInput={setTokenInput}
            onToggleEnabled={(enabled) => void saveAlertSettings({ enabled })}
            onSaveToken={() => void saveAlertSettings({ bot_token: tokenInput })}
            onDiscoverChat={() => void discoverChat()}
            onSendTest={() => void sendTest()}
            busy={alertsBusy}
            busyLabel={alertsBusyLabel}
          />
        )}
      </div>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);


