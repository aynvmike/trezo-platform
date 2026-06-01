// Performance Snapshot — extracted from /dashboard/performance so it can
// render inline on the Overview page (Mike feedback 2026-05-28: Overview
// and Performance covered the same ground; merge into one tab).
//
// Server component. Reads paper_positions + paper_accounts for the
// current user and renders the same scorecard / risk meters / by-strategy
// table that the old Performance page did.

import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { Disclosure } from "@/components/ui/disclosure";

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

type Closed = {
  strategy: string | null;
  realized_pnl_usd: number | null;
  ticker: string;
  side: string;
  exit_at: string | null;
  status: string;
};

const STRATEGY_LABEL: Record<string, string> = {
  stms: "Stock (STMS)",
  orb: "Opening Range Breakout",
  crypto_scalp: "Crypto SCALP",
  crypto_swing: "Crypto SWING",
  crypto_dca: "Crypto DCA",
  wheel_csp: "Wheel — CSP",
  wheel_cc: "Wheel — Covered Call",
  pattern: "Pattern Engine",
  default: "Pattern Engine"
};

function prettyStrategy(s: string | null): string {
  if (!s) return "Other";
  return STRATEGY_LABEL[s] ?? s.replace(/_/g, " ");
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  if (!d) return "—";
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export async function PerformanceSnapshot({ userId }: { userId: string }) {
  const supabase = createClient();

  const [posRes, acctRes] = await Promise.all([
    supabase
      .from("paper_positions")
      .select("strategy, realized_pnl_usd, ticker, side, exit_at, status")
      .eq("user_id", userId)
      .neq("status", "open")
      .order("exit_at", { ascending: false }),
    supabase
      .from("paper_accounts")
      .select("*")
      .eq("user_id", userId)
      .maybeSingle()
  ]);

  // Filter the closed book down to real round-trips. Two gates:
  // (1) realized_pnl_usd actually set (some half-written or stub rows
  //     have null/undefined here — they are not trade outcomes), and
  // (2) exit_at is set (rows with no exit timestamp never actually
  //     closed at the broker; they're stale planner rows from the
  //     pre-reconcile era and should not pollute the win rate).
  const closed = ((posRes.data ?? []) as Closed[]).filter(
    (p) =>
      p.realized_pnl_usd !== null &&
      p.realized_pnl_usd !== undefined &&
      p.exit_at !== null
  );
  const acct = acctRes.data ?? null;

  // --- Performance metrics (mirrors agents/app/paper/performance.py) ---
  // Mike feedback 2026-05-29: scratches (P&L exactly $0) were dragging
  // the win-rate denominator down. The standard convention is that a
  // scratch is neither a win nor a loss — so the win rate is now
  // wins / (wins + losses) and scratches are surfaced as their own
  // count. This matches every trading platform's convention and gives
  // a truthful read when a position closes flat.
  const pnls = closed.map((p) => Number(p.realized_pnl_usd));
  const n = pnls.length;
  const wins = pnls.filter((x) => x > 0);
  const losses = pnls.filter((x) => x < 0);
  const scratches = pnls.filter((x) => x === 0);
  const decisive = wins.length + losses.length;
  const grossProfit = wins.reduce((a, b) => a + b, 0);
  const grossLoss = Math.abs(losses.reduce((a, b) => a + b, 0));
  const total = pnls.reduce((a, b) => a + b, 0);
  const winRate = decisive ? wins.length / decisive : 0;
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 999 : 0;
  const expectancy = decisive ? (grossProfit - grossLoss) / decisive : 0;

  let cum = 0, peak = 0, maxDD = 0;
  for (const x of [...pnls].reverse()) {
    cum += x;
    peak = Math.max(peak, cum);
    maxDD = Math.max(maxDD, peak - cum);
  }

  const byStrat = new Map<string, number[]>();
  for (const p of closed) {
    const k = p.strategy ?? "default";
    const arr = byStrat.get(k) ?? [];
    arr.push(Number(p.realized_pnl_usd));
    byStrat.set(k, arr);
  }
  const stratRows = [...byStrat.entries()]
    .map(([s, ps]) => ({
      strategy: s,
      trades: ps.length,
      winRate: ps.length ? ps.filter((x) => x > 0).length / ps.length : 0,
      pnl: ps.reduce((a, b) => a + b, 0)
    }))
    .sort((a, b) => b.pnl - a.pnl);

  // --- Kill-switch / account health ---
  const halted = Boolean(acct?.trading_halted);
  const haltReason = String(acct?.halt_reason ?? "");
  const todayPnl = Number(acct?.today_realized_pnl_usd ?? 0);
  const weekPnl = Number(acct?.week_realized_pnl_usd ?? 0);
  const dayStart = Number(acct?.day_start_equity_usd ?? 0);
  const weekStart = Number(acct?.week_start_equity_usd ?? 0);
  const dailyLimit = dayStart > 0 ? -0.03 * dayStart : 0;
  const weeklyLimit = weekStart > 0 ? -0.06 * weekStart : 0;
  const consecLosses = Number(acct?.consecutive_losses ?? 0);

  return (
    <section className="space-y-6">
      <div>
        <h2 className="font-serif text-xl text-weave-800 tracking-tight">
          Bot performance
        </h2>
        <p className="text-sm text-weave-500 leading-relaxed mt-1">
          How the bot is actually doing — win rate, profit factor, equity
          curve, by-strategy attribution. Updates every hour from closed
          paper trades.
        </p>
      </div>

      {/* Trading-halt banner */}
      <div
        className={cn(
          "rounded-xl border p-4",
          halted
            ? "border-red-200 bg-red-50"
            : "border-emerald-200 bg-emerald-50"
        )}
      >
        {halted ? (
          <p className="text-sm text-red-800">
            <span className="font-medium">Trading halted.</span> {haltReason}
          </p>
        ) : (
          <p className="text-sm text-emerald-800">
            <span className="font-medium">Trading active.</span> No
            kill-switch is tripped — the bot is clear to take new signals.
          </p>
        )}
      </div>

      {/* Scorecard */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Stat
          label="Closed trades"
          value={String(n)}
          hint={
            n > 0
              ? `${wins.length}W · ${losses.length}L${scratches.length ? ` · ${scratches.length} scratch` : ""}`
              : undefined
          }
        />
        <Stat
          label="Win rate"
          value={decisive ? `${(winRate * 100).toFixed(1)}%` : "—"}
          hint={decisive ? `${wins.length} / ${decisive} decisive` : "no decisive trades yet"}
        />
        <Stat
          label="Profit factor"
          value={decisive ? (profitFactor >= 999 ? "∞" : profitFactor.toFixed(2)) : "—"}
          tone={profitFactor >= 1 ? "good" : profitFactor > 0 ? "bad" : undefined}
        />
        <Stat
          label="Expectancy / trade"
          value={decisive ? usd(expectancy) : "—"}
          tone={expectancy >= 0 ? "good" : "bad"}
        />
        <Stat
          label="Total realized P&L"
          value={usd(total)}
          tone={total >= 0 ? "good" : "bad"}
        />
        <Stat label="Max drawdown" value={usd(-maxDD)} tone={maxDD > 0 ? "bad" : undefined} />
      </div>

      {/* Risk meters */}
      <div>
        <h3 className="font-medium text-weave-800 mb-3">Today &amp; this week</h3>
        <div className="grid sm:grid-cols-3 gap-3">
          <RiskCard
            label="Today's P&L"
            value={usd(todayPnl)}
            limit={dailyLimit < 0 ? `loss kill-switch at ${usd(dailyLimit)} · halts on losses only, never on profits` : "no baseline yet"}
            bad={dailyLimit < 0 && todayPnl <= dailyLimit}
            tone={todayPnl >= 0 ? "good" : "bad"}
          />
          <RiskCard
            label="This week's P&L"
            value={usd(weekPnl)}
            limit={weeklyLimit < 0 ? `loss kill-switch at ${usd(weeklyLimit)} · halts on losses only, never on profits` : "no baseline yet"}
            bad={weeklyLimit < 0 && weekPnl <= weeklyLimit}
            tone={weekPnl >= 0 ? "good" : "bad"}
          />
          <RiskCard
            label="Losing streak"
            value={`${consecLosses} / 3`}
            limit="3 in a row halts the day"
            bad={consecLosses >= 3}
            tone={consecLosses >= 2 ? "bad" : undefined}
          />
        </div>
      </div>

      {/* Per-strategy breakdown — collapsed by default to keep Overview short */}
      <Disclosure
        title="By strategy"
        hint={stratRows.length ? `${stratRows.length} strategies traded` : "no closed trades yet"}
      >
        {stratRows.length === 0 ? (
          <EmptyCard>
            No closed trades yet. Win rate and per-strategy numbers appear once
            the bot has completed some round trips.
          </EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Strategy</th>
                  <th className="px-4 py-3 text-right">Trades</th>
                  <th className="px-4 py-3 text-right">Win rate</th>
                  <th className="px-4 py-3 text-right">Realized P&L</th>
                </tr>
              </thead>
              <tbody>
                {stratRows.map((s) => (
                  <tr key={s.strategy} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-3 text-weave-800">{prettyStrategy(s.strategy)}</td>
                    <td className="px-4 py-3 text-right font-mono">{s.trades}</td>
                    <td className="px-4 py-3 text-right font-mono">
                      {(s.winRate * 100).toFixed(0)}%
                    </td>
                    <td
                      className={cn(
                        "px-4 py-3 text-right font-mono",
                        s.pnl > 0 && "text-emerald-700",
                        s.pnl < 0 && "text-red-600",
                        s.pnl === 0 && "text-weave-500"
                      )}
                    >
                      {usd(s.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Disclosure>

      {/* Recent closed trades — collapsed by default */}
      <Disclosure
        title="Recent closed trades"
        hint={closed.length ? `${Math.min(15, closed.length)} most recent` : "nothing closed yet"}
      >
        {closed.length === 0 ? (
          <EmptyCard>Nothing closed yet.</EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Strategy</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3 text-right">Result</th>
                  <th className="px-4 py-3">When</th>
                </tr>
              </thead>
              <tbody>
                {closed.slice(0, 15).map((p, i) => {
                  const pnl = Number(p.realized_pnl_usd);
                  return (
                    <tr key={i} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {p.ticker}
                      </td>
                      <td className="px-4 py-3 text-weave-600">
                        {prettyStrategy(p.strategy)}
                      </td>
                      <td className="px-4 py-3 text-weave-500">{p.side}</td>
                      <td
                        className={cn(
                          "px-4 py-3 text-right font-mono",
                          pnl > 0 ? "text-emerald-700" : pnl < 0 ? "text-red-600" : "text-weave-500"
                        )}
                      >
                        {pnl > 0 ? "+" : ""}
                        {usd(pnl)}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {timeAgo(p.exit_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Disclosure>
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
  hint
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          !tone && "text-weave-800"
        )}
      >
        {value}
      </p>
      {hint && (
        <p className="mt-1 text-[11px] text-weave-500 leading-tight">{hint}</p>
      )}
    </div>
  );
}

function RiskCard({
  label,
  value,
  limit,
  bad,
  tone
}: {
  label: string;
  value: string;
  limit: string;
  bad: boolean;
  tone?: "good" | "bad";
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        bad ? "border-red-200 bg-red-50" : "border-weave-100 bg-white"
      )}
    >
      <p className="text-[11px] uppercase tracking-widest text-weave-500">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          !tone && "text-weave-800"
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-weave-500">{limit}</p>
    </div>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
      {children}
    </div>
  );
}
