"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

type Check = { name: string; ok: boolean; detail: string };
type Resp = {
  ok: boolean;
  error?: string;
  verdict?: string;
  saved?: Record<string, unknown>;
  live_in_agents?: Record<string, unknown>;
  checks?: Check[];
};

/**
 * Settings Audit panel — Mike's request: prove that the Bot Tuning
 * values reach every agent, surface any hardcoded overrides. One
 * click hits /admin/settings-audit and shows the saved-vs-live diff.
 */
export function SettingsAuditPanel() {
  const [stage, setStage] = useState<"idle" | "running" | "done" | "error">("idle");
  const [r, setR] = useState<Resp | null>(null);

  async function run() {
    setStage("running");
    try {
      const res = await fetch("/api/admin/settings-audit", { method: "GET" });
      const j = (await res.json()) as Resp;
      setR(j);
      setStage(j.ok || j.checks ? "done" : "error");
    } catch (e) {
      setR({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  // Sync agents now (Mike 2026-07-06): clears the agents' 30s settings
  // cache and re-audits, so a save reaches every agent immediately and
  // any REMAINING drift is real (env override / hardcode) — the audit
  // response explains which.
  async function runSync() {
    setStage("running");
    try {
      const res = await fetch("/api/admin/settings-sync", { method: "POST" });
      const j = (await res.json()) as Resp;
      setR(j);
      setStage(j.ok || j.checks ? "done" : "error");
    } catch (e) {
      setR({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-medium text-weave-800">Settings audit</h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
            Proves what you saved here is what the agents actually use.
            Click Run and Trezo asks every agent what value it&apos;s
            running with right now, then compares to your saved Bot
            Tuning row. Catches hardcoded overrides (the kind of bug that
            kept STMS stuck at TCS 750 earlier today).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={run}
            disabled={stage === "running"}
            className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-60"
          >
            {stage === "running" ? "Working…" : "Run audit"}
          </button>
          <button
            type="button"
            onClick={runSync}
            disabled={stage === "running"}
            title="Clears the agents' 30-second settings cache and re-audits — your latest save reaches every agent immediately."
            className="rounded-md border border-weave-300 px-3 py-1.5 text-xs font-medium text-weave-700 hover:bg-weave-50 disabled:opacity-60"
          >
            Sync agents now
          </button>
        </div>
      </div>
      {r && (
        <div className="space-y-2">
          <div
            className={cn(
              "rounded-lg border p-3 text-sm",
              r.ok
                ? "border-emerald-200 bg-emerald-50/60 text-emerald-900"
                : "border-amber-200 bg-amber-50/60 text-amber-900"
            )}
          >
            {r.verdict || r.error || "no verdict"}
          </div>
          {r.checks && r.checks.length > 0 && (
            <div className="rounded-lg border border-weave-100 overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                    <th className="px-3 py-2">Setting</th>
                    <th className="px-3 py-2">Match</th>
                    <th className="px-3 py-2">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {r.checks.map((c) => (
                    <tr key={c.name} className="border-b border-weave-50 last:border-0">
                      <td className="px-3 py-1.5 font-mono text-weave-700">{c.name}</td>
                      <td className="px-3 py-1.5">
                        <span className={cn(
                          "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                          c.ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-700"
                        )}>
                          {c.ok ? "✓ match" : "✗ drift"}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-weave-600">{c.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
