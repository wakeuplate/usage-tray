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

// Windows caps tray tooltips at roughly 64 characters; keep each line short.
function formatResetIn(resetAt: string | null | undefined): string {
  const at = resetAt ? Date.parse(resetAt) : Number.NaN;
  if (!Number.isFinite(at)) return "-";
  let minutes = Math.max(0, Math.round((at - Date.now()) / 60_000));
  const hours = Math.floor(minutes / 60);
  minutes %= 60;
  return `${hours}h${String(minutes).padStart(2, "0")}m`;
}

function traySummary(snapshot: CollectorSnapshot): string {
  const line = (agent: string, label: string) => {
    const window = snapshot.agents[agent]?.windows.five_hour;
    return `${label} ${formatPercent(window?.used_percent)} · ${formatResetIn(window?.reset_at)}`;
  };
  return `5-hour\n${line("claude", "Claude")}\n${line("codex", "Codex")}`;
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

type TrendPoint = { t: number; v: number };
type TrendSeries = { label: string; className: string; dashed?: boolean; points: TrendPoint[]; current: number | null | undefined };

function trendSeries(history: HistorySnapshot[], agentName: string, windowName: string): TrendPoint[] {
  return history
    .map((snapshot) => ({
      t: Date.parse(snapshot.captured_at),
      v: snapshot.agents[agentName]?.windows[windowName]?.used_percent,
    }))
    .filter((point): point is TrendPoint => Number.isFinite(point.t) && typeof point.v === "number" && !Number.isNaN(point.v))
    .sort((a, b) => a.t - b.t);
}

function bucketMax(points: TrendPoint[], start: number, end: number, bucketMs: number): TrendPoint[] {
  const buckets = new Map<number, number>();
  for (const point of points) {
    if (point.t < start || point.t > end) continue;
    const index = Math.floor((point.t - start) / bucketMs);
    const existing = buckets.get(index);
    buckets.set(index, existing === undefined ? point.v : Math.max(existing, point.v));
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([index, v]) => ({ t: start + index * bucketMs + bucketMs / 2, v }));
}

function gapSegments(points: TrendPoint[], gapMs: number): TrendPoint[][] {
  const segments: TrendPoint[][] = [];
  for (const point of points) {
    const current = segments[segments.length - 1];
    if (current && point.t - current[current.length - 1].t <= gapMs) {
      current.push(point);
    } else {
      segments.push([point]);
    }
  }
  return segments;
}

const CHART_W = 300;
const CHART_H = 72;

function TrendChart({
  title,
  rangeLabel,
  series,
  start,
  end,
  bucketMs,
  ticks,
}: {
  title: string;
  rangeLabel: string;
  series: TrendSeries[];
  start: number;
  end: number;
  bucketMs: number;
  ticks: string[];
}) {
  const gradientBase = React.useId().replaceAll(":", "");
  const x = (t: number) => ((t - start) / (end - start)) * CHART_W;
  const y = (v: number) => CHART_H - (clampPercent(v) / 100) * (CHART_H - 6) - 3;
  const hasData = series.some((item) => item.points.length > 0);

  return (
    <section className="agent-panel trend-card">
      <div className="agent-heading">
        <div className="window-meta">
          <span>{title}</span>
        </div>
        <span className="history-count">{rangeLabel}</span>
      </div>
      <div className="trend-legend">
        {series.map((item) => (
          <span key={item.label} className={item.className}>
            <i className={item.dashed ? "dashed" : ""} />
            <b className="trend-name">{item.label}</b>
            <strong>{formatPercent(item.current)}</strong>
          </span>
        ))}
      </div>
      {hasData ? (
        <>
          <div className="trend-plot" role="img" aria-label={`${title} usage, ${rangeLabel}`}>
            <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none">
              <defs>
                {series.map((item, index) =>
                  item.dashed ? null : (
                    <linearGradient key={index} id={`${gradientBase}-${index}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" className={`trend-stop ${item.className}`} stopOpacity="0.22" />
                      <stop offset="100%" className={`trend-stop ${item.className}`} stopOpacity="0" />
                    </linearGradient>
                  ),
                )}
              </defs>
              <line className="trend-grid" x1="0" y1={y(50)} x2={CHART_W} y2={y(50)} />
              <line className="trend-grid" x1="0" y1={y(100)} x2={CHART_W} y2={y(100)} />
              {series.map((item, index) => {
                const bucketed = bucketMax(item.points, start, end, bucketMs);
                return gapSegments(bucketed, bucketMs * 2.5).map((segment, segmentIndex) => {
                  const line = segment
                    .map((point, i) => `${i === 0 ? "M" : "L"}${x(point.t).toFixed(2)},${y(point.v).toFixed(2)}`)
                    .join(" ");
                  const area = `${line} L${x(segment[segment.length - 1].t).toFixed(2)},${CHART_H} L${x(segment[0].t).toFixed(2)},${CHART_H} Z`;
                  return (
                    <g key={`${index}-${segmentIndex}`} className={`trend-series ${item.className}`}>
                      {item.dashed ? null : <path className="trend-fill" d={area} fill={`url(#${gradientBase}-${index})`} />}
                      <path className={`trend-line ${item.dashed ? "dashed" : ""}`} d={line} />
                    </g>
                  );
                });
              })}
            </svg>
          </div>
          <div className="trend-ticks">
            {ticks.map((label, index) => (
              <span key={index}>{label}</span>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">History will appear after the first live reading.</div>
      )}
    </section>
  );
}

function currentUsed(snapshot: CollectorSnapshot | undefined, agent: string, window: string): number | null | undefined {
  return snapshot?.agents[agent]?.windows[window]?.used_percent;
}

function hourTicks(start: number, end: number, steps: number): string[] {
  const labels: string[] = [];
  for (let i = 0; i < steps; i++) {
    const at = new Date(start + ((end - start) * i) / steps);
    labels.push(`${String(at.getHours()).padStart(2, "0")}:00`);
  }
  labels.push("now");
  return labels;
}

function dayTicks(start: number, end: number): string[] {
  const labels: string[] = [];
  const dayMs = 24 * 3600 * 1000;
  for (let at = start; at < end - dayMs / 2; at += dayMs) {
    labels.push(new Date(at).toLocaleDateString("en-US", { weekday: "short" }));
  }
  labels.push("now");
  return labels;
}

function HistoryTrends({ history, snapshot }: { history: HistorySnapshot[]; snapshot?: CollectorSnapshot }) {
  const end = history.reduce((latest, item) => Math.max(latest, Date.parse(item.captured_at) || 0), 0) || Date.now();
  const dayStart = end - 24 * 3600 * 1000;
  const weekStart = end - 7 * 24 * 3600 * 1000;

  return (
    <>
      <TrendChart
        title="5-hour"
        rangeLabel="last 24h"
        start={dayStart}
        end={end}
        bucketMs={30 * 60 * 1000}
        ticks={hourTicks(dayStart, end, 4)}
        series={[
          { label: "Claude", className: "trend-claude", points: trendSeries(history, "claude", "five_hour"), current: currentUsed(snapshot, "claude", "five_hour") },
          { label: "Codex", className: "trend-codex", points: trendSeries(history, "codex", "five_hour"), current: currentUsed(snapshot, "codex", "five_hour") },
        ]}
      />
      <TrendChart
        title="Weekly"
        rangeLabel="last 7 days"
        start={weekStart}
        end={end}
        bucketMs={3 * 3600 * 1000}
        ticks={dayTicks(weekStart, end)}
        series={[
          { label: "Claude", className: "trend-claude", points: trendSeries(history, "claude", "weekly"), current: currentUsed(snapshot, "claude", "weekly") },
          { label: "scoped", className: "trend-claude", dashed: true, points: trendSeries(history, "claude", "weekly_scoped"), current: currentUsed(snapshot, "claude", "weekly_scoped") },
          { label: "Codex", className: "trend-codex", points: trendSeries(history, "codex", "weekly"), current: currentUsed(snapshot, "codex", "weekly") },
        ]}
      />
    </>
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
        setHistory(await invoke<HistorySnapshot[]>("read_history", { limit: 6_000 }));
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
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
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
          Trends
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
            <AgentPanel name="claude" agent={snapshot?.agents.claude} />
            <AgentPanel name="codex" agent={snapshot?.agents.codex} />
          </>
        ) : mode === "history" ? (
          <HistoryTrends history={recentHistory} snapshot={snapshot ?? undefined} />
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


