"use client";

/**
 * Market / industry scanner for the Strategy Lab simulation tab
 * (Mike 2026-07-14): scan the whole market or one industry, tick the
 * names you like, and save them as a CUSTOM watchlist — which then
 * shows up in the simulation picker and the backtest merge on the
 * next render.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type ScanRow = {
  symbol: string;
  price: number;
  d1: number;
  d3: number;
  volume_ratio: number;
};
type ScanResp = {
  error?: string;
  results?: ScanRow[];
  sectors?: { etf: string; name: string }[];
};

export function MarketScanPanel() {
  const router = useRouter();
  const [sector, setSector] = useState("");
  const [sectors, setSectors] = useState<{ etf: string; name: string }[]>([]);
  const [rows, setRows] = useState<ScanRow[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function scan() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const qs = new URLSearchParams({ sector, limit: "24" });
      const r = await fetch(`/api/lab/scan?${qs.toString()}`);
      const body = (await r.json()) as ScanResp;
      if (body.error) setError(body.error);
      else {
        setRows(body.results ?? []);
        if (body.sectors?.length) setSectors(body.sectors);
        setPicked(new Set());
      }
    } catch {
      setError("The scan could not be run — are the agents online?");
    } finally {
      setBusy(false);
    }
  }

  function toggle(sym: string) {
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(sym)) n.delete(sym);
      else n.add(sym);
      return n;
    });
  }

  async function save() {
    if (picked.size === 0 || !name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/watchlists/create", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, tickers: Array.from(picked) })
      });
      const body = (await r.json()) as { ok?: boolean; error?: string; added?: number; name?: string };
      if (body.error) setError(body.error);
      else {
        setNote(
          `Saved "${body.name}" with ${body.added} ticker${body.added === 1 ? "" : "s"} — it is now available in the simulation picker and the backtest merge.`
        );
        setName("");
        setPicked(new Set());
        router.refresh();
      }
    } catch {
      setError("Could not save the watchlist.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-weave-200 bg-white p-5 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-serif text-lg text-weave-800">Scan the market</h3>
          <p className="text-xs text-weave-500 mt-0.5 max-w-xl">
            Hunt beyond the watchlists — the whole market or one industry,
            ranked by 3-day move with volume pace. Tick the names you like
            and save them as a custom watchlist.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor="scan-sector">Industry</Label>
            <select
              id="scan-sector"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="flex h-10 rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
            >
              <option value="">Whole market</option>
              {(sectors.length
                ? sectors
                : [
                    { etf: "XLK", name: "Technology" },
                    { etf: "SMH", name: "Semiconductors" },
                    { etf: "XLF", name: "Financials" },
                    { etf: "XLE", name: "Energy" },
                    { etf: "XLV", name: "Health Care" },
                    { etf: "XLY", name: "Consumer Disc" },
                    { etf: "XLI", name: "Industrials" },
                    { etf: "XLP", name: "Consumer Staples" },
                    { etf: "XLU", name: "Utilities" },
                    { etf: "XLB", name: "Materials" },
                    { etf: "XLRE", name: "Real Estate" },
                    { etf: "XLC", name: "Communications" },
                    { etf: "XBI", name: "Biotech" },
                    { etf: "GDX", name: "Gold Miners" }
                  ]
              ).map((s) => (
                <option key={s.etf} value={s.etf}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <Button onClick={scan} disabled={busy}>
            {busy ? "Scanning…" : "Scan"}
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {note && <p className="text-sm text-emerald-700">{note}</p>}

      {rows.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-weave-500 border-b border-weave-100">
                  <th className="py-2 pr-2" />
                  <th className="py-2 pr-4">Symbol</th>
                  <th className="py-2 pr-4">Price</th>
                  <th className="py-2 pr-4">Today</th>
                  <th className="py-2 pr-4">3-day</th>
                  <th className="py-2 pr-4">Volume vs avg</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    className="border-b border-weave-50 hover:bg-treasure-100/40 cursor-pointer"
                    onClick={() => toggle(r.symbol)}
                  >
                    <td className="py-1.5 pr-2">
                      <input
                        type="checkbox"
                        checked={picked.has(r.symbol)}
                        onChange={() => toggle(r.symbol)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="py-1.5 pr-4 font-medium text-weave-800">{r.symbol}</td>
                    <td className="py-1.5 pr-4">${r.price.toFixed(2)}</td>
                    <td className={"py-1.5 pr-4 " + (r.d1 >= 0 ? "text-emerald-600" : "text-red-600")}>
                      {r.d1 >= 0 ? "+" : ""}
                      {r.d1.toFixed(1)}%
                    </td>
                    <td className={"py-1.5 pr-4 " + (r.d3 >= 0 ? "text-emerald-600" : "text-red-600")}>
                      {r.d3 >= 0 ? "+" : ""}
                      {r.d3.toFixed(1)}%
                    </td>
                    <td className="py-1.5 pr-4">{r.volume_ratio.toFixed(1)}x</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-end gap-2 pt-1">
            <div className="space-y-1">
              <Label htmlFor="scan-name">New watchlist name</Label>
              <Input
                id="scan-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Semis momentum July"
                className="w-64"
              />
            </div>
            <Button onClick={save} disabled={saving || picked.size === 0 || !name.trim()}>
              {saving
                ? "Saving…"
                : `Save ${picked.size || ""} ticker${picked.size === 1 ? "" : "s"} as watchlist`}
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
