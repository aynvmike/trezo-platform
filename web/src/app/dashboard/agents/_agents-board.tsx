"use client";

import { useEffect, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { useLiteRefresh } from "@/lib/use-lite";

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

type FeedMessage = {
  id: string;
  agent_name: string;
  kind: string;
  confidence: number | null;
  payload: Record<string, unknown>;
  created_at: string;
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

function relTime(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 10_000) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return new Date(iso).toLocaleDateString();
}

const KIND_COLOR: Record<string, string> = {
  signal:   "bg-weave-100 text-weave-800",
  approve:  "bg-emerald-100 text-emerald-800",
  veto:     "bg-amber-100 text-amber-800",
  execute:  "bg-treasure-200 text-treasure-800",
  alert:    "bg-red-100 text-red-800",
  error:    "bg-red-100 text-red-800",
  info:     "bg-weave-50 text-weave-600"
};

export function AgentsBoard() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [feed, setFeed]     = useState<FeedMessage[]>([]);
  const [error, setError]   = useState<string | null>(null);

  const reloadAll = useCallback(async () => {
    try {
      const [a, f] = await Promise.all([
        fetch("/api/agents", { cache: "no-store" }).then((r) => r.json()),
        fetch("/api/agents/feed?limit=30", { cache: "no-store" }).then((r) => r.json())
      ]);
      // Defensive — always coerce to arrays so .map() can't blow up
      setAgents(Array.isArray(a?.agents) ? a.agents : []);
      setFeed(Array.isArray(f?.messages) ? f.messages : []);
      setError(a?.error ?? f?.error ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  const refreshMs = useLiteRefresh(5) * 1000;
  useEffect(() => {
    void reloadAll();
    const id = setInterval(reloadAll, refreshMs);
    return () => clearInterval(id);
  }, [reloadAll, refreshMs]);

  async function toggle(name: string, enabled: boolean) {
    setAgents((cur) => cur.map((a) => (a.name === name ? { ...a, enabled } : a)));
    try {
      await fetch(`/api/agents/${name}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled })
      });
    } catch {
      // revert on failure
      setAgents((cur) => cur.map((a) => (a.name === name ? { ...a, enabled: !enabled } : a)));
    }
  }

  async function trigger(name: string) {
    try {
      await fetch(`/api/agents/${name}/trigger`, { method: "POST" });
    } catch {
      setError("Trigger failed");
    }
    await reloadAll();
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      {/* Agents grid */}
      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="font-serif text-xl text-weave-800">Eight agents</h2>
          {error && <span className="text-xs text-amber-700">{error}</span>}
        </div>
        {agents.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-600">
            Agents service unreachable. Make sure it&apos;s running on port 8001
            (double-click <code>start-agents.bat</code>).
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {agents.map((a) => (
              <li key={a.name} className="rounded-xl border border-weave-100 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium text-weave-800 truncate">
                      {PRETTY_NAMES[a.name] ?? a.name}
                    </p>
                    <p className="mt-1 text-[10px] uppercase tracking-widest text-weave-400">
                      {a.role}
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
                    className="text-weave-600 hover:underline"
                  >
                    Run now →
                  </button>
                </div>
                {a.last_error && (
                  <p className="mt-2 text-xs text-red-700">{a.last_error}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Live feed */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">Activity feed</h2>
        <div className="rounded-xl border border-weave-100 bg-white max-h-[640px] overflow-y-auto">
          {feed.length === 0 ? (
            <p className="p-6 text-center text-sm text-weave-500">
              No messages yet. Toggle an agent on and it&apos;ll tick within a minute.
            </p>
          ) : (
            <ul className="divide-y divide-weave-50">
              {feed.map((m) => (
                <li key={m.id} className="px-4 py-3">
                  <div className="flex items-center gap-2 text-xs">
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-widest",
                        KIND_COLOR[m.kind] ?? "bg-weave-50 text-weave-500"
                      )}
                    >
                      {m.kind}
                    </span>
                    <span className="text-weave-500">
                      {PRETTY_NAMES[m.agent_name] ?? m.agent_name}
                    </span>
                    <span className="ml-auto text-weave-400">{relTime(m.created_at)}</span>
                  </div>
                  <pre className="mt-2 text-[11px] text-weave-600 whitespace-pre-wrap break-words font-mono">
                    {JSON.stringify(m.payload, null, 2)}
                  </pre>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
