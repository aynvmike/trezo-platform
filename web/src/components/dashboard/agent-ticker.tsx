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

/**
 * Slim sticky strip below the dashboard header that marquees the latest
 * agent messages — like a stock ticker, in plain words. Updates every 5s.
 */
export function AgentTicker() {
  const [items, setItems] = useState<FeedMessage[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const r = await fetch("/api/agents/feed?limit=12", { cache: "no-store" });
        const j = (await r.json()) as { messages?: FeedMessage[] };
        if (!cancelled) {
          setItems(Array.isArray(j?.messages) ? j.messages : []);
        }
      } catch {
        // ignore — the ticker quietly hides on failure
      }
    }

    void load();
    const id = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (items.length === 0) return null;

  // Duplicate the items so the marquee loops seamlessly
  const looped = [...items, ...items];

  return (
    <div className="border-b border-weave-100 bg-weave-50/50 overflow-hidden">
      <div className="relative">
        <div className="marquee flex gap-6 py-2 px-4 whitespace-nowrap">
          {looped.map((m, i) => (
            <span key={`${m.id}-${i}`} className="inline-flex items-center gap-2 text-xs">
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-widest",
                  KIND_COLOR[m.kind] ?? "bg-weave-50 text-weave-500"
                )}
              >
                {kindLabel(m.kind)}
              </span>
              <span className="font-medium text-weave-700">
                {agentLabel(m.agent_name)}
              </span>
              <span className="text-weave-500">{describeAgentMessage(m)}</span>
              <span className="text-weave-300">·</span>
            </span>
          ))}
        </div>
      </div>

      <style jsx>{`
        .marquee {
          animation: marquee 60s linear infinite;
        }
        .marquee:hover {
          animation-play-state: paused;
        }
        @keyframes marquee {
          from {
            transform: translateX(0);
          }
          to {
            transform: translateX(-50%);
          }
        }
      `}</style>
    </div>
  );
}
