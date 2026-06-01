import { createClient } from "@/lib/supabase/server";
import { PostmortemButton } from "./postmortem-button";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type StrategyStat = {
  n: number;
  wins: number;
  losses: number;
  scratches: number;
  win_rate: number | null;
  total_pnl_usd: number;
  avg_win_usd: number | null;
  avg_loss_usd: number | null;
  median_tcs_winners: number | null;
  median_tcs_losers: number | null;
  median_hold_minutes: number | null;
};

type Suggestion = {
  strategy: string;
  kind: "raise_tcs_floor" | "pause_strategy" | string;
  note: string;
  suggested_tcs_floor?: number;
};

type Insights = {
  configured: boolean;
  lookback_days?: number;
  n?: number;
  by_strategy?: Record<string, StrategyStat>;
  by_cycle?: Record<string, StrategyStat>;
  by_regime?: Record<string, StrategyStat>;
  suggestions?: Suggestion[];
  error?: string;
};

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(0)}%`;
}

/**
 * Learning Insights — Phase 13/14. Renders per-strategy stats over the
 * last 30 days of CLOSED trades for the signed-in user, plus
 * plain-English suggestions. Pure read-only; the suggestions sit
 * informational until Mike applies them in Bot Tuning by hand.
 *
 * Renders nothing when there's no data yet — the panel only earns its
 * spot on the page once a few closes have rolled in.
 */
export async function LearningInsights() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  let data: Insights | null = null;
  try {
    const r = await fetch(
      `${AGENTS_BASE}/learning/insights?` +
        new URLSearchParams({ user_id: user.id, lookback_days: "30" }),
      { cache: "no-store", signal: AbortSignal.timeout(8000) }
    );
    if (r.ok) data = (await r.json()) as Insights;
  } catch {
    data = null;
  }

  if (!data || !data.configured || !data.n || data.n === 0) return null;

  const byStrat = data.by_strategy ?? {};
  const byCycle = data.by_cycle ?? {};
  const suggestions = data.suggestions ?? [];

  // Post-mortem diagnosis breakdown — separate Supabase query.
  // Counts how many of the user's recent trades fall into each
  // diagnosis bucket (held_too_long, optimal, exited_too_early, etc.).
  const { data: diagRows } = await supabase
    .from("trade_outcomes")
    .select("postmortem_diagnosis")
    .eq("user_id", user.id)
    .not("postmortem_diagnosis", "is", null);
  const diagCounts: Record<string, number> = {};
  for (const r of (diagRows ?? []) as { postmortem_diagnosis: string }[]) {
    const k = r.postmortem_diagnosis;
    diagCounts[k] = (diagCounts[k] ?? 0) + 1;
  }
  const DIAG_LABEL: Record<string, string> = {
    optimal: "Optimal exits",
    held_too_long: "Held too long",
    exited_too_early: "Exited too early",
    stop_too_tight: "Stop too tight",
    late_to_stop: "Late to stop",
    no_signal: "No clear signal",
  };
  const DIAG_TONE: Record<string, string> = {
    optimal: "text-emerald-700",
    held_too_long: "text-red-700",
    exited_too_early: "text-amber-700",
    stop_too_tight: "text-amber-700",
    late_to_stop: "text-red-700",
    no_signal: "text-weave-500",
  };

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-4">
      <div>
        <h2 className="font-medium text-weave-800">Learning insights</h2>
        <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
          The bot keeps a ledger of every trade you closed in the last{" "}
          {data.lookback_days ?? 30} days — entry conditions plus the
          outcome — and shows you what worked. {data.n} closed trade
          {data.n === 1 ? "" : "s"} in scope. Suggestions are
          informational; nothing auto-applies.
        </p>
      </div>

      <PostmortemButton />

      {Object.keys(diagCounts).length > 0 ? (
        <div>
          <p className="text-[11px] uppercase tracking-widest text-weave-500 mb-2">
            Your trade patterns
          </p>
          <ul className="grid grid-cols-2 sm:grid-cols-3 gap-1 text-xs">
            {Object.entries(diagCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([d, n]) => (
                <li
                  key={d}
                  className={`flex items-baseline justify-between gap-2 rounded border border-weave-100 px-2 py-1 ${
                    DIAG_TONE[d] ?? "text-weave-700"
                  }`}
                >
                  <span>{DIAG_LABEL[d] ?? d}</span>
                  <span className="font-mono font-medium">{n}</span>
                </li>
              ))}
          </ul>
        </div>
      ) : null}

      {suggestions.length > 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
          <p className="text-xs font-medium text-amber-900 uppercase tracking-widest">
            Suggestions
          </p>
          <ul className="space-y-1">
            {suggestions.map((s, i) => (
              <li key={i} className="text-sm text-amber-900 leading-relaxed">
                {s.note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[640px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
              <th className="px-2 py-2">Strategy</th>
              <th className="px-2 py-2 text-right">Trades</th>
              <th className="px-2 py-2 text-right">Win rate</th>
              <th className="px-2 py-2 text-right">Avg win</th>
              <th className="px-2 py-2 text-right">Avg loss</th>
              <th className="px-2 py-2 text-right">Total P&L</th>
              <th className="px-2 py-2 text-right">TCS W/L</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byStrat)
              .sort((a, b) => b[1].n - a[1].n)
              .map(([strat, s]) => (
                <tr
                  key={strat}
                  className="border-b border-weave-50 last:border-0"
                >
                  <td className="px-2 py-2 font-mono text-weave-800">
                    {strat}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">
                    {s.wins}/{s.losses}
                    {s.scratches ? `+${s.scratches}` : ""}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">
                    {pct(s.win_rate)}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-emerald-700">
                    {usd(s.avg_win_usd)}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-red-700">
                    {usd(s.avg_loss_usd)}
                  </td>
                  <td
                    className={
                      "px-2 py-2 text-right font-mono " +
                      (s.total_pnl_usd >= 0
                        ? "text-emerald-700"
                        : "text-red-700")
                    }
                  >
                    {usd(s.total_pnl_usd)}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-weave-500">
                    {s.median_tcs_winners ?? "—"}/
                    {s.median_tcs_losers ?? "—"}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {Object.keys(byCycle).length > 1 ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-weave-600 hover:text-weave-800">
            Performance by cycle position
          </summary>
          <table className="w-full mt-2 text-xs">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-2 py-1.5">Environment</th>
                <th className="px-2 py-1.5 text-right">Trades</th>
                <th className="px-2 py-1.5 text-right">Win rate</th>
                <th className="px-2 py-1.5 text-right">Total P&L</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byCycle).map(([env, s]) => (
                <tr key={env} className="border-b border-weave-50 last:border-0">
                  <td className="px-2 py-1.5 font-mono text-weave-700">
                    {env}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">{s.n}</td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {pct(s.win_rate)}
                  </td>
                  <td
                    className={
                      "px-2 py-1.5 text-right font-mono " +
                      (s.total_pnl_usd >= 0
                        ? "text-emerald-700"
                        : "text-red-700")
                    }
                  >
                    {usd(s.total_pnl_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </section>
  );
}
