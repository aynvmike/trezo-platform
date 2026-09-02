"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

type Resp = {
  ok: boolean;
  error?: string;
  info?: string;
  details?: Record<string, unknown>;
  kind?: string;
  venue?: string;
  broker?: string;
  fill_price?: number;
  alpaca_order_id?: string;
  alpaca_order_status?: string;
  quantity?: number;
};

/**
 * "Place trade now" — manual one-shot trade sent straight to Trade
 * Execution on the caller's book. TE-10 (audit 2026-09-01): it does NOT
 * pass through the Risk Manager -- no TCS bar, no R:R gate, no per-book
 * open-count cap; only the kill-switch at execution and the book binding
 * stand between the click and the order. Venue is whatever trading_mode
 * resolves to (paper today; the live executor does not exist yet).
 */
export function ManualTradeButton() {
  const router = useRouter();
  const [stage, setStage] = useState<"idle" | "confirm" | "sending" | "done" | "error">("idle");
  const [resp, setResp] = useState<Resp | null>(null);
  const [ticker, setTicker] = useState("");
  const [side, setSide] = useState<"long" | "short">("long");
  const [stopPct, setStopPct] = useState("");
  const [targetPct, setTargetPct] = useState("");

  async function send() {
    setStage("sending");
    try {
      const r = await fetch("/api/admin/manual-trade", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.toUpperCase(),
          side,
          stop_pct: stopPct ? Number(stopPct) / 100 : undefined,
          target_pct: targetPct ? Number(targetPct) / 100 : undefined
        })
      });
      const j = (await r.json()) as Resp;
      setResp(j);
      setStage(j.ok ? "done" : "error");
      if (j.ok) router.refresh();
    } catch (e) {
      setResp({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  const reset = () => { setStage("idle"); setResp(null); };

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div>
        <h2 className="font-serif text-xl text-weave-800">Place a trade now</h2>
        <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
          Manual one-shot trade on your own book. This goes straight to
          Trade Execution and skips the Risk Manager&apos;s checks (no
          confidence bar, no reward-to-risk gate) — only the kill-switch
          can stop it. Paper venue today; live is not built yet.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-5 items-end">
        <div className="space-y-1 sm:col-span-2">
          <label className="block text-[11px] uppercase tracking-widest text-weave-500">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="e.g. AAPL"
            maxLength={10}
            className="w-full rounded-md border border-weave-200 px-3 py-2 text-sm uppercase font-mono"
          />
        </div>
        <div className="space-y-1">
          <label className="block text-[11px] uppercase tracking-widest text-weave-500">Side</label>
          <select
            value={side}
            onChange={(e) => setSide(e.target.value as "long" | "short")}
            className="w-full rounded-md border border-weave-200 px-3 py-2 text-sm"
          >
            <option value="long">Long (buy)</option>
            <option value="short">Short (sell)</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="block text-[11px] uppercase tracking-widest text-weave-500">Stop % (opt)</label>
          <input
            type="number"
            value={stopPct}
            onChange={(e) => setStopPct(e.target.value)}
            placeholder="5"
            min={0.5}
            max={50}
            step={0.5}
            className="w-full rounded-md border border-weave-200 px-3 py-2 text-sm"
          />
        </div>
        <div className="space-y-1">
          <label className="block text-[11px] uppercase tracking-widest text-weave-500">Target % (opt)</label>
          <input
            type="number"
            value={targetPct}
            onChange={(e) => setTargetPct(e.target.value)}
            placeholder="10"
            min={0.5}
            max={100}
            step={0.5}
            className="w-full rounded-md border border-weave-200 px-3 py-2 text-sm"
          />
        </div>
      </div>

      {stage === "idle" && (
        <button
          type="button"
          disabled={!/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)}
          onClick={() => setStage("confirm")}
          className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-60"
        >
          Place trade
        </button>
      )}

      {stage === "confirm" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs space-y-2">
          <p className="font-medium text-amber-900">
            Confirm: {side === "long" ? "BUY" : "SELL"} {ticker} via current venue.
          </p>
          <p className="text-weave-700 leading-relaxed">
            Routes through Risk Manager (may veto) and Trade Execution.
            Sizing comes from Bot Tuning risk slider × current account
            equity. Stop {stopPct || "5"}% / target {targetPct || "10"}%.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={send}
              className="rounded-md bg-weave-700 px-3 py-1 text-xs font-medium text-treasure-50 hover:bg-weave-800"
            >
              Confirm & place
            </button>
            <button
              type="button"
              onClick={reset}
              className="rounded-md border border-weave-200 px-3 py-1 text-xs text-weave-600 hover:bg-weave-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {stage === "sending" && <p className="text-xs text-weave-500">Placing…</p>}

      {stage === "done" && resp?.ok && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 text-xs space-y-1">
          <p className="font-medium text-emerald-900">
            ✓ Executed · venue {(resp.venue ?? resp.broker ?? "paper").toUpperCase()}
          </p>
          <p className="text-weave-700">
            {resp.quantity ? `${resp.quantity} shares ` : ""}
            {resp.fill_price ? `@ $${Number(resp.fill_price).toFixed(2)}` : ""}
            {resp.alpaca_order_id ? ` · order ${String(resp.alpaca_order_id).slice(0, 8)}…` : ""}
            {resp.alpaca_order_status ? ` · ${resp.alpaca_order_status}` : ""}
          </p>
          <button type="button" onClick={reset} className="text-[11px] text-weave-600 underline">
            Place another
          </button>
        </div>
      )}

      {stage === "error" && (
        <div className={cn("rounded-lg border p-3 text-xs space-y-1",
          resp?.info ? "border-amber-200 bg-amber-50/60" : "border-red-200 bg-red-50/60")}>
          <p className={cn("font-medium", resp?.info ? "text-amber-900" : "text-red-800")}>
            {resp?.info ? "✗ Not placed (gate)" : "✗ Failed"}
          </p>
          <p className="text-weave-700">{resp?.info ?? resp?.error ?? "Unknown error."}</p>
          <button type="button" onClick={reset} className="text-[11px] text-weave-600 underline">
            Try again
          </button>
        </div>
      )}
    </section>
  );
}
