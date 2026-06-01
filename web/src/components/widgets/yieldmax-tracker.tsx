"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import {
  saveHolding,
  removeHolding,
  type HoldingResult
} from "@/app/dashboard/yieldmax/_actions";

type Position = {
  id: string;
  ticker: string;
  shares: number;
  cumulative_dist: number;
  drip_enabled: boolean;
  dist_yield_pct: number;
  name?: string | null;
};

type Quote = { symbol: string; current: number; changePercent: number };
type RowStatus = { state: "idle" | "busy" | "saved" | "error"; msg?: string };

export function YieldMaxTracker({ positions }: { positions: Position[] }) {
  const [rows, setRows] = useState<Position[]>(positions);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Record<string, RowStatus>>({});

  // Keep local rows in sync when the server sends fresh data.
  useEffect(() => {
    setRows(positions);
  }, [positions]);

  // Stable signature of the tickers we need quotes for — typing into
  // the Shares input updates rows on every keystroke, but the ticker
  // set is unchanged, so we don't want to refetch quotes for every
  // keystroke. Joining the sorted ticker list gives a stable string
  // that only changes when a position is added / removed / renamed.
  const tickerSignature = rows
    .map((p) => p.ticker)
    .sort()
    .join(",");

  useEffect(() => {
    if (!tickerSignature) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const r = await fetch(`/api/quotes?symbols=${tickerSignature}`, { cache: "no-store" });
        const j = (await r.json()) as { quotes: Quote[]; error?: string };
        if (cancelled) return;
        setError(j.error ?? null);
        const map: Record<string, Quote> = {};
        for (const q of j.quotes ?? []) map[q.symbol] = q;
        setQuotes(map);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to fetch");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [tickerSignature]);

  async function onRemove(id: string) {
    setStatus((s) => ({ ...s, [id]: { state: "busy" } }));
    const fd = new FormData();
    fd.set("position_id", id);
    const res: HoldingResult = await removeHolding(fd);
    if (res.ok) {
      setRows((r) => r.filter((x) => x.id !== id));
      setStatus((s) => {
        const { [id]: _drop, ...rest } = s;
        return rest;
      });
    } else {
      setStatus((s) => ({
        ...s,
        [id]: { state: "error", msg: res.error ?? "Could not remove." }
      }));
    }
  }

  async function onSave(e: React.FormEvent<HTMLFormElement>, id: string) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    fd.set("position_id", id);
    setStatus((s) => ({ ...s, [id]: { state: "busy" } }));
    const res: HoldingResult = await saveHolding(fd);
    if (res.ok) {
      const shares = Number(fd.get("shares") ?? 0);
      const drip = fd.get("drip_enabled") === "on";
      const yld = Number(fd.get("dist_yield_pct") ?? 0);
      setRows((r) =>
        r.map((x) =>
          x.id === id ? { ...x, shares, drip_enabled: drip, dist_yield_pct: yld } : x
        )
      );
      setStatus((s) => ({ ...s, [id]: { state: "saved" } }));
      setTimeout(
        () => setStatus((s) => ({ ...s, [id]: { state: "idle" } })),
        2500
      );
    } else {
      setStatus((s) => ({
        ...s,
        [id]: { state: "error", msg: res.error ?? "Could not save." }
      }));
    }
  }

  const totalValue = rows.reduce((sum, p) => {
    const q = quotes[p.ticker];
    return sum + (q ? p.shares * q.current : 0);
  }, 0);
  const totalDist = rows.reduce((sum, p) => sum + p.cumulative_dist, 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-weave-100 bg-treasure-100/40 p-5">
          <p className="text-xs uppercase tracking-widest text-treasure-700">
            Holdings value
          </p>
          <p className="mt-1 font-serif text-3xl text-weave-800">
            ${totalValue.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </p>
          {error && <p className="mt-2 text-xs text-amber-700">{error}</p>}
          {!error && loading && rows.length > 0 && (
            <p className="mt-2 text-xs text-weave-400">Fetching live prices…</p>
          )}
        </div>
        <div className="rounded-xl border border-weave-100 bg-treasure-100/40 p-5">
          <p className="text-xs uppercase tracking-widest text-treasure-700">
            Distributions to date
          </p>
          <p className="mt-1 font-serif text-3xl text-weave-800">
            ${totalDist.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </p>
          <p className="mt-2 text-xs text-weave-500">
            With DRIP on, each distribution buys more shares — the position
            compounds on its own.
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((p) => {
          const q = quotes[p.ticker];
          const price = q?.current ?? 0;
          const change = q?.changePercent ?? 0;
          const up = change >= 0;
          const value = p.shares * price;
          const st = status[p.id] ?? { state: "idle" };
          const busy = st.state === "busy";
          return (
            <div key={p.id} className="rounded-xl border border-weave-100 bg-white p-5">
              <div className="flex items-center justify-between">
                <p className="font-mono font-medium text-weave-800">{p.ticker}</p>
                {p.name && (
                  <p className="text-[11px] text-weave-500 truncate">{p.name}</p>
                )}
                <button
                  type="button"
                  onClick={() => onRemove(p.id)}
                  disabled={busy}
                  className="text-[10px] uppercase tracking-widest text-weave-400 transition hover:text-red-600 disabled:opacity-40"
                >
                  {busy ? "…" : "Remove"}
                </button>
              </div>
              <p className="mt-3 text-xs uppercase tracking-widest text-weave-500">
                Current value
              </p>
              <p className="mt-1 font-serif text-2xl text-weave-800">
                ${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </p>
              <div className="mt-2 flex items-center justify-between text-sm">
                <span className="text-weave-500">
                  ${price.toFixed(2)}/sh ·{" "}
                  {p.shares.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh
                </span>
                <span
                  className={cn("font-medium", up ? "text-emerald-700" : "text-red-700")}
                >
                  {up ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%
                </span>
              </div>

              <form
                onSubmit={(e) => onSave(e, p.id)}
                className="mt-3 border-t border-weave-50 pt-3 space-y-2"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="text-weave-500">Distributions to date</span>
                  <span className="font-mono text-weave-700">
                    ${p.cumulative_dist.toFixed(2)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <label htmlFor={`sh-${p.id}`} className="text-xs text-weave-500">
                    Shares
                  </label>
                  {/* Controlled input — Mike feedback 2026-05-28: he
                      wants Holdings Value + per-card Current value to
                      reflect the new share count as he types, not only
                      after the Save server round-trip. Local state
                      updates on every change; Save still persists. */}
                  <input
                    id={`sh-${p.id}`}
                    type="number"
                    name="shares"
                    value={p.shares}
                    onChange={(e) => {
                      const next = Number(e.currentTarget.value);
                      const safe = Number.isFinite(next) && next >= 0 ? next : 0;
                      setRows((r) =>
                        r.map((x) => (x.id === p.id ? { ...x, shares: safe } : x))
                      );
                    }}
                    min={0}
                    step="0.0001"
                    className="w-24 rounded border border-weave-200 px-2 py-1 text-xs"
                  />
                </div>
                <label className="flex items-center gap-2 text-xs text-weave-600">
                  <input
                    type="checkbox"
                    name="drip_enabled"
                    defaultChecked={p.drip_enabled}
                    className="accent-weave-600"
                  />
                  Reinvest distributions (DRIP)
                </label>
                <div className="flex items-center gap-2">
                  <label htmlFor={`yld-${p.id}`} className="text-xs text-weave-500">
                    Est. yield %
                  </label>
                  <input
                    id={`yld-${p.id}`}
                    type="number"
                    name="dist_yield_pct"
                    defaultValue={p.dist_yield_pct}
                    min={0}
                    max={500}
                    step={1}
                    className="w-20 rounded border border-weave-200 px-2 py-1 text-xs"
                  />
                  <button
                    type="submit"
                    disabled={busy}
                    className="ml-auto text-xs rounded-md border border-weave-300 px-2.5 py-1 text-weave-700 transition hover:bg-weave-50 disabled:opacity-40"
                  >
                    {busy ? "Saving…" : "Save"}
                  </button>
                </div>
                {st.state === "saved" && (
                  <p className="text-[11px] text-emerald-700">Saved ✓</p>
                )}
                {st.state === "error" && (
                  <p className="text-[11px] text-red-600">{st.msg}</p>
                )}
              </form>
            </div>
          );
        })}
      </div>
    </div>
  );
}
