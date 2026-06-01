"use client";

import { useEffect, useState, useCallback } from "react";
import { cn } from "@/lib/utils";

type AgentInfo = {
  name: string;
  description: string;
  enabled: boolean;
  role: string;
  last_tick_at: string | null;
  tick_count: number;
  message_count: number;
  last_error: string | null;
};

const PRETTY_NAMES: Record<string, string> = {
  pattern_detection: "Pattern Detection",
  risk_manager:      "Risk Manager",
  trade_execution:   "Trade Execution",
  tax_optimizer:     "Tax Optimizer",
  market_sentiment:  "Market Sentiment",
  user_support:      "User Support",
  research:          "Research",
  strategy_discovery: "Strategy Discovery"
};

const CADENCE: Record<string, string> = {
  pattern_detection: "every 60 seconds",
  risk_manager:      "event-driven (reacts to signals)",
  trade_execution:   "event-driven (reacts to approvals)",
  tax_optimizer:     "event-driven (reacts to executions)",
  market_sentiment:  "every 5 minutes",
  user_support:      "on-demand (Q&A)",
  research:          "every 10 minutes",
  strategy_discovery: "every hour"
};

function relTime(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 10_000) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function AgentsSettings() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [error, setError]   = useState<string | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const r = await fetch("/api/agents", { cache: "no-store" });
      const j = (await r.json()) as { agents?: AgentInfo[]; error?: string };
      setAgents(Array.isArray(j?.agents) ? j.agents : []);
      setError(j?.error ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    void reload();
    const id = setInterval(reload, 5000);
    return () => clearInterval(id);
  }, [reload]);

  async function toggle(name: string, enabled: boolean) {
    setAgents((cur) => cur.map((a) => (a.name === name ? { ...a, enabled } : a)));
    try {
      await fetch(`/api/agents/${name}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled })
      });
    } catch {
      setAgents((cur) => cur.map((a) => (a.name === name ? { ...a, enabled: !enabled } : a)));
    }
  }

  async function trigger(name: string) {
    setBusyName(name);
    try {
      await fetch(`/api/agents/${name}/trigger`, { method: "POST" });
    } catch {
      setError("Trigger failed");
    } finally {
      setBusyName(null);
      await reload();
    }
  }

  if (agents.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-600">
        {error
          ? error
          : "Loading agents… If this persists, make sure start-agents.bat is running on port 8001."}
      </div>
    );
  }

  return (
    <>
      {error && (
        <p className="text-xs text-amber-700">{error}</p>
      )}
      <ul className="grid gap-3 sm:grid-cols-2">
        {agents.map((a) => (
          <li key={a.name} className="rounded-xl border border-weave-100 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-weave-800 truncate">
                  {PRETTY_NAMES[a.name] ?? a.name}
                </p>
                <p className="mt-1 text-[10px] uppercase tracking-widest text-weave-400">
                  {a.role} · {CADENCE[a.name] ?? ""}
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={a.enabled}
                onClick={() => toggle(a.name, !a.enabled)}
                className={cn(
                  "relative h-6 w-11 rounded-full transition shrink-0",
                  a.enabled ? "bg-weave-600" : "bg-weave-200"
                )}
                aria-label={`Toggle ${a.name}`}
              >
                <span
                  className={cn(
                    "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition",
                    a.enabled ? "translate-x-5" : "translate-x-0"
                  )}
                />
              </button>
            </div>
            <p className="mt-3 text-sm text-weave-600 leading-relaxed">{a.description}</p>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-weave-500">
              <span>
                Last tick: <span className="text-weave-700">{relTime(a.last_tick_at)}</span> · {a.tick_count} ticks · {a.message_count} msgs
              </span>
              <button
                onClick={() => trigger(a.name)}
                disabled={busyName === a.name}
                className="text-weave-600 hover:underline disabled:opacity-50"
              >
                {busyName === a.name ? "Running…" : "Run now →"}
              </button>
            </div>
            {a.last_error && (
              <p className="mt-2 text-xs text-red-700">{a.last_error}</p>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
