"use client";

import { useState } from "react";

type RunResult = {
  ok: boolean;
  scanned?: number;
  analyzed?: number;
  skipped?: number;
  by_diagnosis?: Record<string, number>;
  error?: string;
};

const DIAG_LABEL: Record<string, string> = {
  optimal: "Optimal",
  held_too_long: "Held too long",
  exited_too_early: "Exited too early",
  stop_too_tight: "Stop too tight",
  late_to_stop: "Late to stop",
  no_signal: "No clear signal",
};

const DIAG_COLOR: Record<string, string> = {
  optimal: "text-emerald-700",
  held_too_long: "text-red-700",
  exited_too_early: "text-amber-700",
  stop_too_tight: "text-amber-700",
  late_to_stop: "text-red-700",
  no_signal: "text-weave-500",
};

/**
 * Client-side "Run post-mortem" button. Hits /api/learning/postmortem,
 * shows a quick status while the analyzer churns through the user's
 * trade_outcomes rows, then renders the diagnosis breakdown inline.
 *
 * Designed to live INSIDE the LearningInsights server component so
 * the user can analyze and see the results in one place.
 */
export function PostmortemButton() {
  const [busy, setBusy] = useState(false);
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);

  async function run() {
    setBusy(true);
    setResult(null);
    try {
      const r = await fetch(
        `/api/learning/postmortem${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      const j = (await r.json()) as RunResult;
      setResult(j);
    } catch (e) {
      setResult({
        ok: false,
        error: e instanceof Error ? e.message : "Network error",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-weave-100 bg-weave-50/50 p-3 space-y-2">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <p className="text-xs font-medium text-weave-800">
            Trade post-mortem
          </p>
          <p className="text-[11px] text-weave-500 leading-relaxed">
            Replay every closed trade against historical candles. Flags
            trades where you held too long, exited too early, or had
            your stop too tight. The bot uses this to understand your
            patterns and surface them in the suggestions above.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-[11px] text-weave-600 flex items-center gap-1">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
            />
            Re-analyze
          </label>
          <button
            type="button"
            onClick={run}
            disabled={busy}
            className="rounded-md bg-weave-600 px-3 py-1.5 text-xs font-medium text-treasure-50 hover:bg-weave-700 disabled:opacity-50"
          >
            {busy ? "Analyzing..." : "Run post-mortem"}
          </button>
        </div>
      </div>

      {result && (
        <div className="space-y-1">
          {result.ok ? (
            <>
              <p className="text-[11px] text-weave-700">
                Scanned {result.scanned ?? 0}, analyzed {result.analyzed ?? 0}
                {result.skipped ? `, skipped ${result.skipped}` : ""}.
              </p>
              {result.by_diagnosis && Object.keys(result.by_diagnosis).length > 0 ? (
                <ul className="grid grid-cols-2 sm:grid-cols-3 gap-1 text-[11px]">
                  {Object.entries(result.by_diagnosis)
                    .sort((a, b) => b[1] - a[1])
                    .map(([d, n]) => (
                      <li
                        key={d}
                        className={`flex items-baseline justify-between gap-2 ${
                          DIAG_COLOR[d] ?? "text-weave-700"
                        }`}
                      >
                        <span>{DIAG_LABEL[d] ?? d}</span>
                        <span className="font-mono font-medium">{n}</span>
                      </li>
                    ))}
                </ul>
              ) : null}
            </>
          ) : (
            <p className="text-[11px] text-red-700">
              {result.error ?? "Analyzer failed."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
