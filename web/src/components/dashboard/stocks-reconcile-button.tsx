"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Resp = {
  ok: boolean;
  error?: string;
  users_touched?: number;
  updated?: number;
  inserted?: number;
  closed?: number;
  details?: { user_id: string; notes: string[] }[];
};

/**
 * "Sync stock positions with Alpaca" button. Triggers the agents-side
 * /stocks/reconcile endpoint, which patches Trezo's open paper_positions
 * to match Alpaca's actual holdings. Use after a discrepancy is spotted
 * (Mike: SOFI showed qty 3 on Trezo, qty 7 on Alpaca — the broker is
 * always the truth).
 */
export function StocksReconcileButton() {
  const router = useRouter();
  const [stage, setStage] = useState<"idle" | "running" | "done" | "error">("idle");
  const [resp, setResp] = useState<Resp | null>(null);

  async function run() {
    setStage("running");
    setResp(null);
    try {
      const r = await fetch("/api/stocks/reconcile", { method: "POST" });
      const j = (await r.json()) as Resp;
      setResp(j);
      setStage(j.ok ? "done" : "error");
      if (j.ok) router.refresh();
    } catch (e) {
      setResp({ ok: false, error: e instanceof Error ? e.message : "request failed" });
      setStage("error");
    }
  }

  const summary =
    stage === "running"
      ? "Reconciling..."
      : stage === "done"
        ? `Done — patched ${resp?.updated ?? 0}, inserted ${resp?.inserted ?? 0}, closed ${resp?.closed ?? 0}`
        : stage === "error"
          ? `Failed — ${resp?.error ?? "unknown error"}`
          : "Sync stock positions with Alpaca";

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="font-medium text-weave-800 text-sm">
            Stock positions vs Alpaca
          </p>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-0.5">
            When Trezo&apos;s open-positions table disagrees with what Alpaca
            actually holds (qty / entry price / side), click Reconcile.
            Alpaca is the truth; Trezo&apos;s view gets patched to match,
            and any phantom rows are closed.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={stage === "running"}
          className="shrink-0 rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-60"
          title="Pull Alpaca positions and update Trezo's local view to match."
        >
          {summary}
        </button>
      </div>
      {stage === "done" && resp?.details && resp.details.length > 0 && (
        <ul className="text-[11px] text-weave-500 leading-relaxed list-disc list-inside max-h-32 overflow-y-auto">
          {resp.details.flatMap((d) =>
            (d.notes ?? []).map((n, i) => <li key={`${d.user_id}-${i}`}>{n}</li>)
          )}
        </ul>
      )}
    </div>
  );
}
