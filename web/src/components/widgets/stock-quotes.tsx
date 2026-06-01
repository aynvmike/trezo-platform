"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type StockQuote = {
  symbol: string;
  current: number;
  change: number;
  changePercent: number;
};

export function StockQuotes({
  symbols,
  refreshSec = 60
}: {
  symbols: string[];
  refreshSec?: number;
}) {
  const [data, setData] = useState<StockQuote[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetch(`/api/quotes?symbols=${symbols.join(",")}`, {
          cache: "no-store"
        });
        const j = (await r.json()) as { quotes: StockQuote[]; error?: string };
        if (cancelled) return;
        if (j.error) setError(j.error);
        else setError(null);
        setData(j.quotes ?? []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to fetch");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, refreshSec * 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbols, refreshSec]);

  if (loading && data.length === 0) {
    return (
      <div className="rounded-xl border border-weave-100 bg-white">
        <div className="h-40 animate-pulse" />
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-weave-100 bg-white overflow-hidden">
      {error && (
        <p className="px-4 py-2 text-xs text-amber-700 bg-amber-50 border-b border-amber-100">
          {error}
        </p>
      )}
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[420px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
            <th className="px-4 py-3">Ticker</th>
            <th className="px-4 py-3 text-right">Price</th>
            <th className="px-4 py-3 text-right">Change</th>
          </tr>
        </thead>
        <tbody>
          {data.length === 0 && (
            <tr>
              <td colSpan={3} className="px-4 py-6 text-center text-weave-400">
                No quotes yet.
              </td>
            </tr>
          )}
          {data.map((q) => {
            const up = q.changePercent >= 0;
            return (
              <tr key={q.symbol} className="border-b border-weave-50 last:border-0">
                <td className="px-4 py-3 font-medium text-weave-800">{q.symbol}</td>
                <td className="px-4 py-3 text-right font-mono text-weave-800">
                  ${q.current.toFixed(2)}
                </td>
                <td
                  className={cn(
                    "px-4 py-3 text-right font-medium",
                    up ? "text-emerald-700" : "text-red-700"
                  )}
                >
                  {up ? "▲" : "▼"} {Math.abs(q.changePercent).toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </div>
  );
}
