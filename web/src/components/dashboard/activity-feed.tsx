"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
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
  maxHeight = "640px"
}: {
  limit?: number;
  refreshSec?: number;
  showPayload?: boolean;
  maxHeight?: string;
}) {
  const [items, setItems] = useState<FeedMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const r = await fetch(`/api/agents/feed?limit=${limit}`, { cache: "no-store" });
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
    const id = setInterval(load, refreshSec * 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [limit, refreshSec]);

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
              <span className="ml-auto text-weave-400">{relTime(m.created_at)}</span>
            </div>
            {showPayload && (
              <p className="mt-1.5 text-sm text-weave-700 leading-relaxed">
                {describeAgentMessage(m)}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
