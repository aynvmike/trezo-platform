"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  {
    key: "patterns",
    label: "Live Patterns",
    hint: "What the bot sees RIGHT NOW across your watchlist"
  },
  {
    key: "backtest",
    label: "Backtest",
    hint: "Replay history for one strategy on one ticker / watchlist"
  },
  {
    key: "simulation",
    label: "Simulation",
    hint: "Stress-test ALL strategies across a recent window"
  }
] as const;

export function StrategyLabTabs() {
  const params = useSearchParams();
  const active = (params.get("tab") || "patterns").toLowerCase();
  return (
    <nav className="rounded-xl border border-weave-100 bg-white p-1.5 flex items-center gap-1 overflow-x-auto">
      {TABS.map((t) => {
        const isActive = active === t.key;
        return (
          <Link
            key={t.key}
            href={`/dashboard/strategy-lab?tab=${t.key}`}
            className={cn(
              "flex-1 min-w-fit rounded-lg px-4 py-2 transition text-sm",
              isActive
                ? "bg-weave-600 text-treasure-50 shadow-sm"
                : "text-weave-700 hover:bg-weave-50"
            )}
            title={t.hint}
          >
            <span className="font-medium">{t.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
