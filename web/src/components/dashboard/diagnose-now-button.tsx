"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

type Reject = { symbol?: string; status?: string; reason?: string; submitted_at?: string };
type VetoEx = { ticker?: string; tcs?: number; reason?: string };
type Resp = {
  ok: boolean;
  error?: string;
  venue?: string;
  configured?: boolean;
  verdict?: string;
  next_action?: string;
  account?: {
    equity?: number; cash?: number; buying_power?: number;
    status?: string; trading_blocked?: boolean;
    options_approved_level?: number; daytrade_count?: number;
  };
  clock?: { is_open?: boolean; next_open?: string; next_close?: string };
  orders_today?: { total?: number; by_status?: Record<string, number>; rejects?: Reject[] };
  vetoes_today?: { total?: number; by_bucket?: Record<string, number>; examples?: VetoEx[] };
  checks?: { name: string; ok: boolean; detail: string }[];
};

/**
 * "Diagnose now" — one click pulls account + clock + today's orders +
 * today's vetoes from Trezo's own Alpaca client and gives a
 * one-paragraph verdict on whether anything is reaching the broker.
 */
export function DiagnoseNowButton() {
  const [stage, setStage] = useState<"idle" | "running" | "done" | "error">("idle");
  const [r, setR] = useState<Resp | null>(null);

  async function run() {
    setStage("running");
    try {
      const res = await fetch("/api/admin/diagnose", { method: "GET" });
      const j = (await res.json()) as Resp;
      setR(j);
      setStage(j.ok ? "done" : "error");
    } catch (e) {
      setR({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">Diagnose now</h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
            Trezo asks Alpaca directly and combines the answer with
            today&apos;s Risk Manager vetoes. One paragraph, plain
            English. Use when something feels off but the UI doesn&apos;t
            show why.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={stage === "running"}
          className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-60"
        >
          {stage === "running" ? "Running…" : "Run diagnostic"}
        </button>
      </div>
      {r && (
        <div className="space-y-3">
          <div
            className={cn(
              "rounded-lg border p-3 space-y-1",
              r.ok && (r.verdict ?? "").toLowerCase().includes("healthy")
                ? "border-emerald-200 bg-emerald-50/60"
                : r.ok
                ? "border-amber-200 bg-amber-50/60"
                : "border-red-200 bg-red-50/60"
            )}
          >
            <p className="text-sm font-medium text-weave-800">
              {r.verdict || r.error || "No verdict."}
            </p>
            {r.next_action && (
              <p className="text-xs text-weave-700 leading-relaxed">
                <span className="font-medium">Next action:</span> {r.next_action}
              </p>
            )}
          </div>

          {r.account && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <Fact label="Venue" value={(r.venue ?? "paper").toUpperCase()} />
              <Fact label="Equity" value={usd(r.account.equity)} />
              <Fact label="Buying power" value={usd(r.account.buying_power)} />
              <Fact label="Trading blocked" value={r.account.trading_blocked ? "YES" : "no"} bad={r.account.trading_blocked} />
            </div>
          )}

          {r.clock && (
            <p className="text-[11px] text-weave-500">
              Market <span className="font-medium text-weave-700">{r.clock.is_open ? "OPEN" : "closed"}</span>
              {r.clock.next_open ? ` · next open ${new Date(r.clock.next_open).toLocaleString()}` : ""}
              {r.clock.next_close ? ` · next close ${new Date(r.clock.next_close).toLocaleString()}` : ""}
            </p>
          )}

          {r.orders_today && (
            <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3 text-xs space-y-1">
              <p className="font-medium text-weave-800">
                Orders at Alpaca today — {r.orders_today.total ?? 0}
              </p>
              {r.orders_today.by_status && Object.keys(r.orders_today.by_status).length > 0 && (
                <p className="text-weave-600">
                  {Object.entries(r.orders_today.by_status).map(([k, v]) => `${v} ${k}`).join(" · ")}
                </p>
              )}
              {(r.orders_today.rejects ?? []).length > 0 && (
                <ul className="mt-1 space-y-0.5 text-[11px] text-weave-500">
                  {r.orders_today.rejects!.map((x, i) => (
                    <li key={i}>
                      <span className="font-mono font-medium text-weave-700">{x.symbol}</span> {x.status} — {x.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {r.vetoes_today && (
            <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3 text-xs space-y-1">
              <p className="font-medium text-weave-800">
                Risk Manager vetoes today — {r.vetoes_today.total ?? 0}
              </p>
              {r.vetoes_today.by_bucket && Object.keys(r.vetoes_today.by_bucket).length > 0 && (
                <p className="text-weave-600">
                  {Object.entries(r.vetoes_today.by_bucket).map(([k, v]) => `${v} ${k}`).join(" · ")}
                </p>
              )}
            </div>
          )}

          {r.checks && (
            <details className="text-[11px] text-weave-500">
              <summary className="cursor-pointer">Raw checks</summary>
              <ul className="mt-1 space-y-0.5 font-mono">
                {r.checks.map((c, i) => (
                  <li key={i} className={c.ok ? "text-weave-600" : "text-red-700"}>
                    {c.ok ? "✓" : "✗"} {c.name} — {c.detail}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

function Fact({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className={cn(
      "rounded border px-2 py-1.5",
      bad ? "border-red-200 bg-red-50/60" : "border-weave-100 bg-white"
    )}>
      <p className="text-[10px] uppercase tracking-widest text-weave-500">{label}</p>
      <p className={cn("font-mono text-xs font-medium", bad ? "text-red-700" : "text-weave-800")}>
        {value}
      </p>
    </div>
  );
}

function usd(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}
