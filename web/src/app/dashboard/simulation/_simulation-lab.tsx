"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type WlTicker = { ticker: string; asset_type: string };
type Watchlist = {
  id: string;
  name: string;
  is_default: boolean;
  tickers: WlTicker[];
};

type Trade = {
  symbol: string;
  strategy: string;
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  outcome: string;
  bars_held: number;
  exit_reason: string;
  entry_tcs?: number;
  entry_pattern?: string | null;
};

type SymRow = {
  symbol: string;
  strategy?: string;
  trades?: number;
  wins?: number;
  losses?: number;
  pnl_pct?: number;
  peak_tcs?: number;
  peak_strategy?: string | null;
  error?: string;
};

type StratBucket = {
  trades: number;
  wins: number;
  losses: number;
  pnl_usd: number;
  avg_tcs?: number | null;
  tcs_min?: number | null;
  tcs_max?: number | null;
};

type CurvePoint = { date: string; equity: number; realized_today: number };

type RunResult = {
  compare_all?: boolean;
  starting_equity: number;
  ending_equity: number;
  return_pct: number;
  trade_fraction: number;
  window_days: number;
  tcs_threshold: number;
  symbols_tested: number;
  symbols_skipped: number;
  per_symbol: SymRow[];
  by_strategy: Record<string, StratBucket>;
  trades: Trade[];
  equity_curve: CurvePoint[];
  error?: string;
};

const PRESET_EQUITIES = [1_000, 5_000, 10_000, 25_000, 100_000];
const PRESET_DAYS = [5, 7, 14, 30];

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

function stratLabel(s: string): string {
  return (
    {
      default: "Core scoring",
      pattern: "Pattern Engine",
      stms: "Stock Bot",
      orb: "ORB breakout",
      crypto: "Crypto momentum",
      extended: "Extended swing"
    } as Record<string, string>
  )[s] ?? s;
}

// Plain-English explanations for the beginner audience. Hovers over the
// strategy name reveal "what this strategy is hunting for" so a brand-new
// trader can read the Simulation Lab without having to look anything up.
function stratTooltip(s: string): string {
  return (
    {
      default:
        "Core scoring: Trezo's baseline. Scores every setup the same way live agents do — trend + volume + momentum + market regime.",
      pattern:
        "Pattern Engine: scans for classic chart patterns (flags, bases, breakouts) and rates setup quality. Best for swing entries.",
      stms:
        "Stock Bot (STMS): small-cap momentum hunter. Looks for $1–$20 stocks breaking out on 5×-average volume. Higher risk, higher reward.",
      orb:
        "ORB breakout: enters when price breaks the first 15-minute range after the open and exits by midday. Best for liquid stocks gapping at open.",
      crypto:
        "Crypto momentum: 24/7 trend follower for liquid coins. Buys strength on the higher timeframe, scales out on weakness.",
      extended:
        "Extended swing: multi-day pullback strategy. Buys names that have pulled back to their 50-day average inside an uptrend. Hold 3–10 days."
    } as Record<string, string>
  )[s] ?? "No description available yet for this strategy.";
}

// A strategy-name cell that renders the friendly label plus an ⓘ marker.
// Hovering anywhere on the cell shows the plain-English tooltip via the
// native title attribute — works without any tooltip library.
function StrategyLabel({ s }: { s: string }) {
  const label = stratLabel(s);
  const tip = stratTooltip(s);
  return (
    <span
      title={tip}
      className="inline-flex items-center gap-1 cursor-help"
    >
      {label}
      <span
        aria-hidden
        className="text-[10px] text-weave-400 leading-none"
      >
        ⓘ
      </span>
    </span>
  );
}

export function SimulationLab({ watchlists }: { watchlists: Watchlist[] }) {
  const router = useRouter();

  // Default selection: the user's "default" watchlist if it has tickers,
  // else the first non-empty list, else the first list.
  const initialId = useMemo(() => {
    const def =
      watchlists.find((w) => w.is_default && w.tickers.length > 0) ??
      watchlists.find((w) => w.tickers.length > 0) ??
      watchlists[0];
    return def?.id ?? "";
  }, [watchlists]);

  const [watchlistId, setWatchlistId] = useState(initialId);
  const [days, setDays] = useState(7);
  const [equity, setEquity] = useState(10_000);
  const [tcs, setTcs] = useState(650);
  const [compareAll, setCompareAll] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [promoted, setPromoted] = useState<Set<string>>(new Set());
  const [promoting, setPromoting] = useState<string | null>(null);

  const selectedList = watchlists.find((w) => w.id === watchlistId);
  const tickers = (selectedList?.tickers ?? [])
    .filter((t) => t.asset_type !== "option")
    .map((t) => t.ticker);
  const defaultList = watchlists.find((w) => w.is_default);
  const defaultTickers = new Set(
    (defaultList?.tickers ?? []).map((t) => t.ticker.toUpperCase())
  );

  async function run() {
    if (!watchlistId) {
      setError("Pick a watchlist to simulate.");
      return;
    }
    if (tickers.length === 0) {
      setError(
        "That watchlist has no stocks or crypto to simulate. Add a ticker first."
      );
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const qs = new URLSearchParams({
        watchlist_id: watchlistId,
        days: String(days),
        starting_equity: String(equity),
        tcs_threshold: String(tcs),
        compare_all: compareAll ? "true" : "false"
      });
      const r = await fetch(`/api/simulation/run?${qs.toString()}`);
      const body = (await r.json()) as RunResult;
      if (body.error) setError(body.error);
      else setResult(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : "simulation failed");
    } finally {
      setLoading(false);
    }
  }

  async function promote(ticker: string) {
    setPromoting(ticker);
    try {
      const r = await fetch("/api/watchlists/promote", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ticker })
      });
      const j = await r.json();
      if (j.error) {
        setError(j.error);
      } else {
        setPromoted((p) => {
          const next = new Set(p);
          next.add(ticker.toUpperCase());
          return next;
        });
        router.refresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "promote failed");
    } finally {
      setPromoting(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-4">
        <div className="grid sm:grid-cols-4 gap-4">
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="sim-watchlist" className="text-xs">
              Watchlist
            </Label>
            <select
              id="sim-watchlist"
              value={watchlistId}
              onChange={(e) => setWatchlistId(e.target.value)}
              disabled={loading}
              className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
            >
              {watchlists.length === 0 && <option value="">No watchlists</option>}
              {watchlists.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                  {w.is_default ? " (default)" : ""} · {w.tickers.length}{" "}
                  ticker{w.tickers.length === 1 ? "" : "s"}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-weave-500 leading-relaxed">
              Run any watchlist — your testing list, a thematic basket, or
              Core Winners. Manage watchlists on the{" "}
              <a
                href="/dashboard/watchlists"
                className="underline hover:text-weave-700"
              >
                Watchlists page
              </a>
              .
            </p>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Window (days)</Label>
            <div className="flex flex-wrap gap-1.5">
              {PRESET_DAYS.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDays(d)}
                  disabled={loading}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition",
                    days === d
                      ? "border-weave-400 bg-weave-50 text-weave-800"
                      : "border-weave-200 text-weave-500 hover:bg-weave-50"
                  )}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="sim-tcs" className="text-xs">
              Signal TCS
            </Label>
            <Input
              id="sim-tcs"
              type="number"
              min={300}
              max={1000}
              step={10}
              value={tcs}
              onChange={(e) => setTcs(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Starting equity</Label>
          <div className="flex flex-wrap gap-1.5">
            {PRESET_EQUITIES.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => setEquity(e)}
                disabled={loading}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs transition",
                  equity === e
                    ? "border-weave-400 bg-weave-50 text-weave-800"
                    : "border-weave-200 text-weave-500 hover:bg-weave-50"
                )}
              >
                {usd(e)}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={compareAll}
            disabled={loading}
            onChange={(e) => setCompareAll(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-weave-300 accent-treasure-600"
          />
          <span className="text-sm text-weave-700">
            Test every strategy on every ticker
            <span className="block text-xs text-weave-500">
              On: each strategy runs independently — one row per
              (ticker, strategy) so you see how all six performed in
              the window. Off: per stock, only the strategy with the
              most trades is kept (closer to one live agent).
            </span>
          </span>
        </label>

        <div className="flex items-center gap-3 flex-wrap">
          <Button onClick={run} disabled={loading || tickers.length === 0}>
            {loading
              ? "Running…"
              : `Replay ${selectedList?.name ?? "watchlist"} · last ${days}d${compareAll ? " · all strategies" : ""}`}
          </Button>
          <p className="text-xs text-weave-500">
            Each trade is sized at 25% of starting equity. {compareAll ? "Every strategy is scored per stock — same comparison the multi-strategy backtest uses." : "The strategy is chosen per stock — same selection the live bot uses."}
          </p>
        </div>
        {error && (
          <p className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </div>

      {/* Results */}
      {result && (
        <>
          <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat
              label="Starting equity"
              value={usd(result.starting_equity)}
            />
            <Stat
              label="Ending equity"
              value={usd(result.ending_equity)}
              tone={
                result.ending_equity >= result.starting_equity ? "good" : "bad"
              }
            />
            <Stat
              label={`Return over ${result.window_days}d`}
              value={`${result.return_pct >= 0 ? "+" : ""}${result.return_pct}%`}
              tone={result.return_pct >= 0 ? "good" : "bad"}
            />
            <Stat
              label="Tickers tested"
              value={`${result.symbols_tested} of ${result.symbols_tested + result.symbols_skipped}`}
            />
          </section>

          {result.equity_curve.length > 1 && (
            <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-2">
              <h2 className="font-serif text-xl text-weave-800">Equity curve</h2>
              <EquityCurve
                curve={result.equity_curve}
                starting={result.starting_equity}
              />
            </section>
          )}

          <section className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-2">
              <h3 className="font-medium text-weave-800">By strategy</h3>
              <StrategyBucketsTable buckets={result.by_strategy} />
            </div>
            <div className="rounded-xl border border-weave-100 bg-white p-4 space-y-2">
              <h3 className="font-medium text-weave-800">By ticker {result.compare_all ? "× strategy" : ""}</h3>
              {result.compare_all && (
                <p className="text-[11px] text-weave-500">
                  Each (ticker, strategy) pair that fired at least one
                  trade gets its own row.
                </p>
              )}
              <SymbolTable
                rows={result.per_symbol}
                defaultTickers={defaultTickers}
                promoted={promoted}
                promoting={promoting}
                onPromote={promote}
              />
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="font-serif text-xl text-weave-800">
              Trade-by-trade timeline ({result.trades.length})
            </h2>
            {result.trades.length === 0 ? (
              <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
                No trades fired in this window — try a lower Signal TCS or a
                longer window.
              </div>
            ) : (
              <TimelineTable trades={result.trades} />
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">
        {label}
      </p>
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
    </div>
  );
}

function StrategyBucketsTable({
  buckets
}: {
  buckets: Record<string, StratBucket>;
}) {
  const rows = Object.entries(buckets).sort(
    (a, b) => b[1].pnl_usd - a[1].pnl_usd
  );
  if (rows.length === 0) {
    return (
      <p className="text-xs text-weave-500">No strategy fired in this window.</p>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
          <th className="py-2">Strategy</th>
          <th className="py-2 text-right">Trades</th>
          <th className="py-2 text-right">Wins / Losses</th>
          <th className="py-2 text-right">Avg TCS (range)</th>
          <th className="py-2 text-right">P&amp;L</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([s, b]) => (
          <tr key={s} className="border-b border-weave-50 last:border-0">
            <td className="py-2 text-weave-700"><StrategyLabel s={s} /></td>
            <td className="py-2 text-right font-mono">{b.trades}</td>
            <td className="py-2 text-right font-mono text-weave-500">
              {b.wins} / {b.losses}
            </td>
            <td className="py-2 text-right font-mono text-weave-500">
              {typeof b.avg_tcs === "number" ? (
                <>
                  {b.avg_tcs}
                  {typeof b.tcs_min === "number" &&
                    typeof b.tcs_max === "number" && (
                      <span className="ml-1 text-[10px] text-weave-400">
                        ({b.tcs_min}–{b.tcs_max})
                      </span>
                    )}
                </>
              ) : (
                "—"
              )}
            </td>
            <td
              className={cn(
                "py-2 text-right font-mono font-medium",
                b.pnl_usd >= 0 ? "text-emerald-700" : "text-red-600"
              )}
            >
              {b.pnl_usd >= 0 ? "+" : ""}
              {usd(b.pnl_usd)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SymbolTable({
  rows,
  defaultTickers,
  promoted,
  promoting,
  onPromote
}: {
  rows: SymRow[];
  defaultTickers: Set<string>;
  promoted: Set<string>;
  promoting: string | null;
  onPromote: (t: string) => void;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
          <th className="py-2">Symbol</th>
          <th className="py-2">Strategy</th>
          <th className="py-2 text-right">Trades</th>
          <th className="py-2 text-right">P&amp;L%</th>
          <th className="py-2 text-right">Action</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, idx) => {
          const sym = r.symbol.toUpperCase();
          const rowKey = `${r.symbol}__${r.strategy ?? "_"}__${idx}`;
          const alreadyOnCore = defaultTickers.has(sym);
          const justPromoted = promoted.has(sym);
          const isPromoting = promoting === sym;
          const positive = (r.pnl_pct ?? 0) > 0;
          return (
            <tr key={rowKey} className="border-b border-weave-50 last:border-0">
              <td className="py-2 font-mono font-medium text-weave-800">
                {r.symbol}
              </td>
              <td className="py-2 text-xs text-weave-600">
                {r.error ? (
                  <span className="text-amber-700">{r.error}</span>
                ) : (r.trades ?? 0) > 0 ? (
                  <StrategyLabel s={r.strategy ?? ""} />
                ) : (
                  <span title="No strategy fired in this window — showing the one that came closest.">
                    <span className="text-weave-400">closest: </span>
                    <StrategyLabel s={r.peak_strategy ?? r.strategy ?? ""} />
                  </span>
                )}
              </td>
              <td className="py-2 text-right font-mono">
                {(r.trades ?? 0) > 0
                  ? r.trades
                  : r.peak_tcs && r.peak_tcs > 0
                    ? <span className="text-[10px] text-weave-400">peak {r.peak_tcs}</span>
                    : 0}
              </td>
              <td
                className={cn(
                  "py-2 text-right font-mono",
                  (r.pnl_pct ?? 0) >= 0 ? "text-emerald-700" : "text-red-600"
                )}
              >
                {r.pnl_pct === undefined
                  ? "—"
                  : `${r.pnl_pct >= 0 ? "+" : ""}${r.pnl_pct}%`}
              </td>
              <td className="py-2 text-right">
                {alreadyOnCore || justPromoted ? (
                  <span className="text-[10px] uppercase tracking-widest text-emerald-700">
                    On Core
                  </span>
                ) : positive && !r.error ? (
                  <button
                    type="button"
                    onClick={() => onPromote(r.symbol)}
                    disabled={isPromoting}
                    className="rounded-md border border-weave-200 px-2 py-0.5 text-[11px] text-weave-700 hover:bg-weave-50 disabled:opacity-50"
                  >
                    {isPromoting ? "Promoting…" : "Promote →"}
                  </button>
                ) : (
                  <span className="text-[10px] text-weave-300">—</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TimelineTable({ trades }: { trades: Trade[] }) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
            <th className="px-4 py-3">Entered</th>
            <th className="px-4 py-3">Exited</th>
            <th className="px-4 py-3">Symbol</th>
            <th className="px-4 py-3">Strategy</th>
            <th className="px-4 py-3 text-right">P&amp;L</th>
            <th className="px-4 py-3">Outcome</th>
            <th className="px-4 py-3">Why entered</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i} className="border-b border-weave-50 last:border-0">
              <td className="px-4 py-2.5 text-xs text-weave-500">
                {t.entry_date}
              </td>
              <td className="px-4 py-2.5 text-xs text-weave-500">
                {t.exit_date}
              </td>
              <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
                {t.symbol}
              </td>
              <td className="px-4 py-2.5 text-weave-700">
                <StrategyLabel s={t.strategy} />
              </td>
              <td
                className={cn(
                  "px-4 py-2.5 text-right font-mono font-medium",
                  t.pnl_pct >= 0 ? "text-emerald-700" : "text-red-700"
                )}
              >
                {t.pnl_pct >= 0 ? "+" : ""}
                {t.pnl_pct}%
              </td>
              <td className="px-4 py-2.5">
                <span
                  className={cn(
                    "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                    t.outcome === "win"
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-red-100 text-red-800"
                  )}
                >
                  {t.outcome}
                </span>
              </td>
              <td className="px-4 py-2.5 text-xs text-weave-600">
                {t.entry_tcs ? (
                  <>
                    <span className="font-mono">TCS {t.entry_tcs}</span>
                    {t.entry_pattern && (
                      <span className="block text-[10px] text-weave-400">
                        {t.entry_pattern.replace(/_/g, " ")}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-weave-400">Signal</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EquityCurve({
  curve,
  starting
}: {
  curve: CurvePoint[];
  starting: number;
}) {
  const W = 720;
  const H = 220;
  const padX = 36;
  const padY = 16;
  const values = curve.map((p) => p.equity);
  const hi = Math.max(...values, starting);
  const lo = Math.min(...values, starting);
  const span = hi - lo || 1;
  const n = curve.length;
  const xf = (i: number) => padX + (i / Math.max(1, n - 1)) * (W - 2 * padX);
  const yf = (v: number) => padY + (1 - (v - lo) / span) * (H - 2 * padY);
  const line = curve.map((p, i) => `${xf(i)},${yf(p.equity)}`).join(" ");
  const startY = yf(starting);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label="Simulated equity curve"
    >
      <line
        x1={padX}
        x2={W - padX}
        y1={startY}
        y2={startY}
        stroke="#cbd5e1"
        strokeDasharray="3 4"
      />
      <text x={padX + 4} y={startY - 4} fontSize="9" fill="#888">
        starting {usd(starting)}
      </text>
      <polyline points={line} fill="none" stroke="#6c8e7f" strokeWidth={2} />
      {curve.map((p, i) => (
        <circle
          key={i}
          cx={xf(i)}
          cy={yf(p.equity)}
          r={2.5}
          fill={p.realized_today >= 0 ? "#10b981" : "#f87171"}
        >
          <title>
            {p.date} · {usd(p.equity)} ({p.realized_today >= 0 ? "+" : ""}
            {usd(p.realized_today)})
          </title>
        </circle>
      ))}
    </svg>
  );
}
