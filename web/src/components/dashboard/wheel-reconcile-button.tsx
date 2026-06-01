"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Resp = {
  ok: boolean;
  error?: string;
  users_touched?: number;
  rows_closed?: number;
};

/**
 * "Reconcile with broker" button. One click triggers the same Alpaca
 * reconciliation the Options Scanner runs every 30 minutes — any
 * open modeled Wheel leg with no matching contract at the broker is
 * closed_manual. Use after wiping a paper account, switching brokers,
 * or whenever the modeled book and Alpaca disagree.
 */
export function WheelReconcileButton() {
  const router = useRouter();
  const [stage, setStage] = useState<"idle" | "running" | "done" | "error">("idle");
  const [resp, setResp] = useState<Resp | null>(null);

  async function run() {
    setStage("running");
    try {
      const r = await fetch("/api/wheel/reconcile", { method: "POST" });
      const j = (await r.json()) as Resp;
      setResp(j);
      setStage(j.ok ? "done" : "error");
      if (j.ok) router.refresh();
    } catch (e) {
      setResp({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  const label =
    stage === "running"
      ? "Reconciling…"
      : stage === "done"
      ? `✓ Reconciled — ${resp?.rows_closed ?? 0} stale leg(s) closed`
      : stage === "error"
      ? `✗ Failed — ${resp?.error ?? "unknown error"}`
      : "Reconcile modeled book with broker";

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4 flex items-center justify-between gap-3 flex-wrap">
      <div className="min-w-0">
        <p className="font-medium text-weave-800 text-sm">
          Modeled book vs broker
        </p>
        <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-0.5">
          The Wheel planner can drift out of sync if a paper account is
          reset or you switch brokers. Reconcile closes any modeled leg
          that has no matching contract at the broker — Alpaca is the
          truth, the planner follows.
        </p>
      </div>
      <button
        type="button"
        onClick={run}
        disabled={stage === "running"}
        className="shrink-0 rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-60"
        title="Run the same broker-reconciliation the agent runs every 30 minutes."
      >
        {label}
      </button>
    </div>
  );
}
