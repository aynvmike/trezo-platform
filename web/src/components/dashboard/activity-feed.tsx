"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useLiteRefresh } from "@/lib/use-lite";
import {
  type FeedMessage,
  describeAgentMessage,
  agentLabel,
  kindLabel,
  KIND_COLOR
} from "@/lib/agent-message";

function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 10_000) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function ActivityFeed({
  limit = 30,
  refreshSec = 5,
  showPayload = true,
  maxHeight = "640px",
  accountKey,
}: {
  limit?: number;
  refreshSec?: number;
  showPayload?: boolean;
  maxHeight?: string;
  accountKey?: string;
}) {
  const [items, setItems] = useState<FeedMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  const effMs = useLiteRefresh(refreshSec) * 1000;

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const r = await fetch(`/api/agents/feed?limit=${limit}${accountKey ? `&account=${encodeURIComponent(accountKey)}` : ""}`, { cache: "no-store" });
        const j = (await r.json()) as { messages?: FeedMessage[]; error?: string };
        if (cancelled) return;
        setItems(Array.isArray(j?.messages) ? j.messages : []);
        setError(j?.error ?? null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load");
        }
      }
    }

    void load();
    const id = setInterval(load, effMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [limit, effMs, accountKey]);

  if (items.length === 0 && !error) {
    return (
      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-center text-sm text-weave-500">
        No agent activity yet. Toggle an agent on or click &ldquo;Run now&rdquo; in
        Settings → Agents to see messages flow.
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border border-weave-100 bg-white overflow-y-auto"
      style={{ maxHeight }}
    >
      {error && (
        <p className="px-4 py-2 text-xs text-amber-700 bg-amber-50 border-b border-amber-100">
          {error}
        </p>
      )}
      <ul className="divide-y divide-weave-50">
        {items.map((m) => (
          <li key={m.id} className="px-4 py-3">
            <div className="flex items-center gap-2 text-xs">
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-widest",
                  KIND_COLOR[m.kind] ?? "bg-weave-50 text-weave-500"
                )}
              >
                {kindLabel(m.kind)}
              </span>
              <span className="text-weave-500">{agentLabel(m.agent_name)}</span>
              {m.book_label && <span className="text-weave-600 font-medium">{m.book_label}</span>}
              <span className="ml-auto text-weave-400">{relTime(m.created_at)}</span>
            </div>
            {showPayload && (
              <p className="mt-1.5 text-sm text-weave-700 leading-relaxed">
                {describeAgentMessage(m)}
              </p>
            )}
            {showPayload && m.payload?.event === "market_opportunity_library" && Array.isArray(m.payload.opportunities) && (
              <details className="mt-2 text-xs text-weave-600">
                <summary className="cursor-pointer font-medium">View trade possibilities and requirements</summary>
                <ul className="mt-2 space-y-2">{(m.payload.opportunities as Record<string, unknown>[]).map((idea, index) => <li key={String(idea.opportunity_id ?? index)}>
                  <span className="font-medium">{String(idea.ticker ?? "Market")} · {String(idea.market_direction ?? "unverified")} · {String(idea.strategy ?? "").replace(/_/g, " ")}</span>
                  <span className="block">{String(idea.capability_status ?? "unverified")}: {String(idea.capability_reason ?? "Availability has not been verified.")}</span>
                </li>)}</ul>
              </details>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
