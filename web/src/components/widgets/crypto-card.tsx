"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type CryptoPrice = {
  symbol: string;
  name: string;
  priceUsd: number;
  change24h: number;
};

function fmtUsd(n: number): string {
  if (n >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (n >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

export function CryptoCards({
  symbols = ["XRP", "ETH", "SOL"],
  refreshSec = 30
}: {
  symbols?: string[];
  refreshSec?: number;
}) {
  const [data, setData] = useState<CryptoPrice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const r = await fetch(`/api/crypto?symbols=${symbols.join(",")}`, {
          cache: "no-store"
        });
        const j = (await r.json()) as { prices: CryptoPrice[]; error?: string };
        if (cancelled) return;
        if (j.error) setError(j.error);
        else setError(null);
        setData(j.prices ?? []);
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
      <div className="grid gap-3 sm:grid-cols-3">
        {symbols.map((s) => (
          <div key={s} className="h-24 rounded-xl border border-weave-100 bg-white animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div>
      {error && (
        <p className="mb-3 text-xs text-amber-700">
          {error} — showing last cached values.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        {data.map((p) => {
          const up = p.change24h >= 0;
          return (
            <div
              key={p.symbol}
              className="rounded-xl border border-weave-100 bg-white p-4"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs uppercase tracking-widest text-weave-500">
                  {p.name}
                </p>
                <span className="text-[10px] font-medium text-weave-400">{p.symbol}</span>
              </div>
              <p className="mt-2 font-serif text-2xl text-weave-800">
                ${fmtUsd(p.priceUsd)}
              </p>
              <p
                className={cn(
                  "mt-1 text-sm font-medium",
                  up ? "text-emerald-700" : "text-red-700"
                )}
              >
                {up ? "▲" : "▼"} {Math.abs(p.change24h).toFixed(2)}%{" "}
                <span className="font-normal text-weave-400">24h</span>
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
