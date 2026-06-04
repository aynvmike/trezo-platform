"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type Trade = {
  entry_index: number;
  exit_index: number;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  outcome: string;
  bars_held: number;
  exit_reason: string;
  entry_tcs?: number;
  entry_pattern?: string | null;
};

// One strategy's outcome over a symbol's history.
type StratResult = {
  strategy: string;
  bars: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  profit_factor: number;
  expectancy_pct: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  tcs_threshold: number;
  trade_log: Trade[];
  // Diagnostic: highest TCS seen during this run, even if no trade fired.
  peak_tcs?: number;
  peak_tcs_direction?: string;
};

// A single-strategy run carries its own candle series.
type Result = StratResult & {
  symbol: string;
  candles?: { c: number }[];
  error?: string;
};

// An all-strategy run shares one candle series across every strategy.
type CompareResult = {
  symbol: string;
  candles: { c: number }[];
  strategies: StratResult[];
  best_strategy: string | null;
  // Across-strategy peak when no strategy traded.
  peak_tcs?: number;
  peak_strategy?: string | null;
  error?: string;
};

type WlTicker = { ticker: string; asset_type: string };
type Watchlist = {
  id: string;
  name: string;
  is_default: boolean;
  tickers: WlTicker[];
};

type RowState = {
  status: "pending" | "running" | "ok" | "error";
  error?: string;
  result?: Result;
  compare?: CompareResult;
};

type Mode = "single" | "watchlist";

// Every directional strategy is backtestable — the engine scores each
// bar and simulates a long entry. Options and Wheel are not directional
// stop/target trades, so they are proved through paper trading instead.
const STRATEGIES = [
  { value: "default", label: "Default — flat scoring" },
  { value: "pattern", label: "Pattern Engine — candlestick scoring" },
  { value: "stms", label: "STMS — small-cap momentum" },
  { value: "orb", label: "ORB — opening-range breakout" },
  { value: "crypto", label: "Crypto — momentum modes" },
  { value: "extended", label: "Extended — multi-day swing" }
];

const STRATEGY_NAME: Record<string, string> = {
  default: "Default",
  pattern: "Pattern Engine",
  stms: "STMS",
  orb: "ORB",
  crypto: "Crypto",
  extended: "Extended"
};

// Plain-language descriptions used in tooltips + the "What each strategy
// means" disclosure. Default is the flat-scoring fallback — it weighs
// every factor equally and never tilts toward a strategy family.
const STRATEGY_DESC: Record<string, string> = {
  default:
    "Flat scoring — every factor weighed equally. The Pattern Engine's score with no strategy-specific tilt. Use it as the neutral baseline.",
  pattern:
    "Pattern Engine bias — leans on the candlestick-pattern factor (hammers, engulfings, morning stars) and the trend/MACD pair. Best for swing setups on liquid names.",
  stms:
    "Small-cap momentum — favours volume, breakout and momentum. Runs in the 7-11 AM ET window on $1-$20 stocks up 10%+ on 5x volume.",
  orb:
    "Opening Range Breakout — favours the breakout and volume factors. Runs 9:35-11:30 AM ET, trades a confirmed move out of the first 5-minute range.",
  crypto:
    "Crypto momentum — favours volume, RSI bands and Bollinger width. Runs 24/7 on liquid coins, detects SCALP / SWING / DCA modes.",
  extended:
    "Extended swing — favours EMA stack, multi-day breakouts and pullbacks. Holds across sessions (GTC bracket orders)."
};

function stratName(v: string) {
  return STRATEGY_NAME[v] ?? v;
}

function stratDesc(v: string) {
  return STRATEGY_DESC[v] ?? "";
}

// Profit factor reads as "999" internally when there were no losses
// (division by zero guard). Render it more honestly.
function fmtPF(pf: number, trades: number): string {
  if (!Number.isFinite(pf)) return "—";
  if (trades === 0) return "—";
  if (pf >= 100) return "∞";
  return pf.toFixed(2);
}
function pfTooltip(pf: number, trades: number): string {
  if (trades === 0) return "No trades fired in this window.";
  if (pf >= 100) return "Every trade was a winner — no losses to divide by.";
  if (pf >= 1) return `Won ${pf.toFixed(2)}x what was lost. Above 1 = net profitable.`;
  return `Won ${pf.toFixed(2)}x what was lost. Below 1 = net unprofitable.`;
}

function pctClass(v: number) {
  return v >= 0 ? "text-emerald-700" : "text-red-700";
}

function fmtPct(v: number) {
  return `${v >= 0 ? "+" : ""}${v}%`;
}

// The strategy a comparison landed on — the engine's pick, or the
// highest-return strategy if nothing actually traded.
function pickBest(c: CompareResult): StratResult {
  if (c.best_strategy) {
    const m = c.strategies.find((s) => s.strategy === c.best_strategy);
    if (m) return m;
  }
  const sorted = c.strategies
    .slice()
    .sort((a, b) => b.total_return_pct - a.total_return_pct);
  return sorted[0] ?? c.strategies[0];
}

type RowView = {
  strat: StratResult;
  candles: { c: number }[];
  stratLabel: string;
  isCompare: boolean;
  compare?: CompareResult;
};

function rowView(state: RowState): RowView | null {
  if (state.compare) {
    const c = state.compare;
    const best = pickBest(c);
    return {
      strat: best,
      candles: c.candles ?? [],
      stratLabel: c.best_strategy ? stratName(best.strategy) : "—",
      isCompare: true,
      compare: c
    };
  }
  if (state.result) {
    return {
      strat: state.result,
      candles: state.result.candles ?? [],
      stratLabel: stratName(state.result.strategy),
      isCompare: false
    };
  }
  return null;
}

export function BacktestRunner({ watchlists }: { watchlists: Watchlist[] }) {
  const router = useRouter();
  const hasWatchlistTickers = watchlists.some((w) => w.tickers.length > 0);

  const [mode, setMode] = useState<Mode>(
    hasWatchlistTickers ? "watchlist" : "single"
  );
  const [compareAll, setCompareAll] = useState(true);
  const [symbol, setSymbol] = useState("");
  const [watchlistId, setWatchlistId] = useState(() => {
    const seeded =
      watchlists.find((w) => w.is_default && w.tickers.length > 0) ??
      watchlists.find((w) => w.tickers.length > 0) ??
      watchlists[0];
    return seeded?.id ?? "";
  });
  const [strategy, setStrategy] = useState("default");
  const [tcs, setTcs] = useState(650);
  const [stopPct, setStopPct] = useState(5);
  const [targetPct, setTargetPct] = useState(10);
  // Starting capital for the P&L display tiles below each result. The
  // backtest engine returns total_return_pct (compounded); multiplying
  // by this gives a dollar Net P&L the user can actually feel. Default
  // $10k is the standard Trezo paper starting balance.
  const [startingCapital, setStartingCapital] = useState(10000);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Single-symbol results — one for each run shape.
  const [result, setResult] = useState<Result | null>(null);
  const [compareSingle, setCompareSingle] = useState<CompareResult | null>(null);

  // Whole-watchlist results, keyed by ticker.
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [ranList, setRanList] = useState<{
    name: string;
    order: string[];
    compare: boolean;
  } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const cancelRef = useRef(false);

  function riskParams() {
    return {
      tcs_threshold: String(tcs),
      stop_pct: String(Math.max(1, Math.min(50, stopPct)) / 100),
      target_pct: String(Math.max(1, Math.min(100, targetPct)) / 100)
    };
  }

  function singleQuery(sym: string) {
    return new URLSearchParams({
      symbol: sym,
      strategy,
      ...riskParams()
    }).toString();
  }

  function compareQuery(sym: string) {
    return new URLSearchParams({ symbol: sym, ...riskParams() }).toString();
  }

  function clearResults() {
    setResult(null);
    setCompareSingle(null);
    setRows({});
    setRanList(null);
    setExpanded(null);
  }

  async function runSingle() {
    const sym = symbol.trim().toUpperCase();
    if (!sym) {
      setError("Enter a ticker symbol to backtest.");
      return;
    }
    setLoading(true);
    setError(null);
    clearResults();
    try {
      if (compareAll) {
        const r = await fetch(`/api/backtest/compare?${compareQuery(sym)}`);
        const body = (await r.json()) as CompareResult;
        if (body.error) setError(body.error);
        else {
          setCompareSingle(body);
          router.refresh();
        }
      } else {
        const r = await fetch(`/api/backtest?${singleQuery(sym)}`);
        const body = (await r.json()) as Result;
        if (body.error) setError(body.error);
        else {
          setResult(body);
          router.refresh();
        }
      }
    } catch {
      setError("The backtest could not be run — please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function runWatchlist() {
    const wl = watchlists.find((w) => w.id === watchlistId);
    if (!wl) {
      setError("Pick a watchlist to backtest.");
      return;
    }
    // Options are not directional stop/target trades — skip them.
    const testable = wl.tickers.filter((t) => t.asset_type !== "option");
    if (testable.length === 0) {
      setError("That watchlist has no stocks or crypto to backtest.");
      return;
    }
    setLoading(true);
    setError(null);
    clearResults();
    cancelRef.current = false;

    const order = testable.map((t) => t.ticker);
    setRanList({ name: wl.name, order, compare: compareAll });
    const init: Record<string, RowState> = {};
    order.forEach((t) => {
      init[t] = { status: "pending" };
    });
    setRows(init);

    // Sequential — one symbol at a time keeps the agents service and the
    // price-data providers from being hammered, and lets results stream in.
    for (const t of order) {
      if (cancelRef.current) break;
      setRows((p) => ({ ...p, [t]: { status: "running" } }));
      try {
        if (compareAll) {
          const r = await fetch(`/api/backtest/compare?${compareQuery(t)}`);
          const body = (await r.json()) as CompareResult;
          if (body.error) {
            setRows((p) => ({ ...p, [t]: { status: "error", error: body.error } }));
          } else {
            setRows((p) => ({ ...p, [t]: { status: "ok", compare: body } }));
          }
        } else {
          const r = await fetch(`/api/backtest?${singleQuery(t)}`);
          const body = (await r.json()) as Result;
          if (body.error) {
            setRows((p) => ({ ...p, [t]: { status: "error", error: body.error } }));
          } else {
            setRows((p) => ({ ...p, [t]: { status: "ok", result: body } }));
          }
        }
      } catch {
        setRows((p) => ({
          ...p,
          [t]: { status: "error", error: "Could not reach the backtest service." }
        }));
      }
    }

    if (cancelRef.current) {
      setRows((p) => {
        const next = { ...p };
        for (const k of Object.keys(next)) {
          if (next[k].status === "pending") {
            next[k] = { status: "error", error: "Stopped before this ran" };
          }
        }
        return next;
      });
    }
    setLoading(false);
    router.refresh();
  }

  function run() {
    if (mode === "single") runSingle();
    else runWatchlist();
  }

  function stop() {
    cancelRef.current = true;
  }

  const selectedList = watchlists.find((w) => w.id === watchlistId);
  const selectedCount = selectedList
    ? selectedList.tickers.filter((t) => t.asset_type !== "option").length
    : 0;

  const runLabel = (() => {
    if (loading) return "Running…";
    if (mode === "watchlist") {
      const n = selectedCount || 0;
      const s = n === 1 ? "" : "s";
      return compareAll
        ? `Find the best strategy for ${n} symbol${s}`
        : `Run on ${n} symbol${s}`;
    }
    return compareAll ? "Compare every strategy" : "Run backtest";
  })();

  return (
    <div className="space-y-6">
      {/* What do you want to test? */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-weave-500">Backtest:</span>
        {(
          [
            { id: "watchlist" as Mode, label: "A whole watchlist" },
            { id: "single" as Mode, label: "One symbol" }
          ]
        ).map((m) => (
          <button
            key={m.id}
            type="button"
            disabled={loading}
            onClick={() => {
              setMode(m.id);
              setError(null);
            }}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs transition disabled:opacity-50",
              mode === m.id
                ? "border-weave-400 bg-weave-50 text-weave-800"
                : "border-weave-200 text-weave-500 hover:bg-weave-50"
            )}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Test every strategy, keep the best */}
      <label className="flex items-start gap-2.5 cursor-pointer">
        <input
          type="checkbox"
          checked={compareAll}
          disabled={loading}
          onChange={(e) => {
            setCompareAll(e.target.checked);
            setError(null);
          }}
          className="mt-0.5 h-4 w-4 rounded border-weave-300 accent-treasure-600"
        />
        <span className="text-sm text-weave-700">
          Test every strategy and keep the best one for each symbol
          <span className="block text-xs text-weave-500">
            No single strategy suits every stock. With this on, Trezo runs all
            six strategies and picks the strongest one per symbol — leave it
            off to test just one strategy you choose.
          </span>
        </span>
      </label>

      {/* Controls */}
      <div className="rounded-xl border border-weave-100 bg-white p-5">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          {mode === "single" ? (
            <div className="space-y-1">
              <Label htmlFor="bt-symbol">Ticker</Label>
              <Input
                id="bt-symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="AMD or BTC"
                maxLength={8}
              />
            </div>
          ) : (
            <div className="space-y-1 col-span-2 sm:col-span-1">
              <Label htmlFor="bt-watchlist">Watchlist</Label>
              <select
                id="bt-watchlist"
                value={watchlistId}
                onChange={(e) => setWatchlistId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
              >
                {watchlists.length === 0 && <option value="">No watchlists</option>}
                {watchlists.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name} ({w.tickers.length})
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="space-y-1 col-span-2 sm:col-span-1">
            <Label htmlFor="bt-strategy">Strategy</Label>
            <select
              id="bt-strategy"
              value={compareAll ? "__all__" : strategy}
              disabled={compareAll}
              onChange={(e) => setStrategy(e.target.value)}
              className={cn(
                "flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500",
                compareAll && "opacity-50 cursor-not-allowed"
              )}
            >
              {compareAll && <option value="__all__">All strategies</option>}
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="bt-tcs">Signal TCS</Label>
            <Input
              id="bt-tcs"
              type="number"
              min={300}
              max={1000}
              step={10}
              value={tcs}
              onChange={(e) => setTcs(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="bt-stop">Stop %</Label>
            <Input
              id="bt-stop"
              type="number"
              min={1}
              max={50}
              step={1}
              value={stopPct}
              onChange={(e) => setStopPct(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="bt-target">Target %</Label>
            <Input
              id="bt-target"
              type="number"
              min={1}
              max={100}
              step={1}
              value={targetPct}
              onChange={(e) => setTargetPct(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="bt-cap">Starting capital ($)</Label>
            <Input
              id="bt-cap"
              type="number"
              min={100}
              max={10_000_000}
              step={500}
              value={startingCapital}
              onChange={(e) => setStartingCapital(Number(e.target.value) || 10000)}
            />
            <p className="text-[10px] text-weave-500">
              Used to compute Net $ P&amp;L below — backtest math is %-based.
            </p>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          <Button onClick={run} disabled={loading}>
            {runLabel}
          </Button>
          {loading && mode === "watchlist" && (
            <button
              type="button"
              onClick={stop}
              className="rounded-md border border-weave-200 px-3 py-2 text-xs text-weave-600 hover:bg-weave-50"
            >
              Stop
            </button>
          )}
          <span className="text-xs text-weave-500">
            {compareAll
              ? "Every strategy is tested with the same TCS, stop and target. Testing all six takes a little longer per symbol."
              : mode === "watchlist"
                ? "Every stock and crypto on the list is tested with these same settings, one after another."
                : "Stocks test ~2 years of daily history; crypto tests ~1 year."}
          </span>
        </div>
        {error && (
          <p className="mt-3 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </div>

      {/* Single-symbol, single-strategy result */}
      {mode === "single" && !compareAll && result && (
        <SingleResult result={result} startingCapital={startingCapital} />
      )}

      {/* Single-symbol, all-strategy comparison */}
      {mode === "single" && compareAll && compareSingle && (
        <CompareView data={compareSingle} startingCapital={startingCapital} />
      )}

      {/* Whole-watchlist result */}
      {ranList && (
        <WatchlistResults
          listName={ranList.name}
          order={ranList.order}
          compare={ranList.compare}
          rows={rows}
          expanded={expanded}
          onToggle={(t) => setExpanded((cur) => (cur === t ? null : t))}
        />
      )}
    </div>
  );
}

/* ---------- single-symbol, single-strategy ---------- */

function SingleResult({ result, startingCapital }: { result: Result; startingCapital: number }) {
  return (
    <>
      <div>
        <h2 className="font-serif text-xl text-weave-800 mb-1">
          {result.symbol} — {stratName(result.strategy)}
        </h2>
        <p className="text-sm text-weave-500">
          {result.bars} bars tested · signal threshold {result.tcs_threshold} TCS ·{" "}
          {result.trades} trades
        </p>
      </div>

      {result.trades === 0 ? (
        <EmptyRun tcs={result.tcs_threshold} peak={result.peak_tcs} peakDirection={result.peak_tcs_direction} />
      ) : (
        <>
          <MetricsGrid r={result} startingCapital={startingCapital} />
          {result.candles && result.candles.length > 1 && (
            <div>
              <h3 className="font-medium text-weave-800 mb-2">
                Where the strategy traded
              </h3>
              <BacktestChart candles={result.candles} trades={result.trade_log} />
            </div>
          )}
          <div>
            <h3 className="font-medium text-weave-800 mb-2">
              Recent simulated trades
            </h3>
            <TradeTable trades={result.trade_log} />
          </div>
        </>
      )}
    </>
  );
}

/* ---------- single-symbol, all strategies compared ---------- */

function CompareView({ data, startingCapital }: { data: CompareResult; startingCapital: number }) {
  const best = pickBest(data);
  const [selected, setSelected] = useState(best.strategy);
  const shown =
    data.strategies.find((s) => s.strategy === selected) ?? best;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-serif text-xl text-weave-800">
          {data.symbol} — every strategy compared
        </h2>
        <p className="text-sm text-weave-500">
          {data.best_strategy
            ? `Best strategy for ${data.symbol}: ${stratName(data.best_strategy)}`
            : data.peak_tcs && data.peak_tcs > 0
              ? `No strategy crossed TCS ${shown.tcs_threshold}. The strongest read was TCS ${data.peak_tcs}${data.peak_strategy ? ` via ${stratName(data.peak_strategy)}` : ""} — try a threshold below that.`
              : "No strategy produced a trade over this history — try a lower TCS."}
        </p>
      </div>

      <StrategyBreakdown
        strategies={data.strategies}
        best={data.best_strategy}
        selected={selected}
        onSelect={setSelected}
      />
      <p className="text-xs text-weave-500">
        Tap a strategy to see its trades on the chart below.
      </p>

      <div className="space-y-3 border-t border-weave-50 pt-4">
        <h3 className="font-medium text-weave-800">
          {stratName(shown.strategy)} on {data.symbol}
        </h3>
        {shown.trades === 0 ? (
          <EmptyRun tcs={shown.tcs_threshold} peak={shown.peak_tcs} peakDirection={shown.peak_tcs_direction} />
        ) : (
          <MetricsGrid r={shown} startingCapital={startingCapital} />
        )}
        {data.candles.length > 1 && (
          <BacktestChart candles={data.candles} trades={shown.trade_log} />
        )}
        {shown.trades > 0 && <TradeTable trades={shown.trade_log} />}
      </div>
    </div>
  );
}

/* ---------- whole-watchlist results ---------- */

function WatchlistResults({
  listName,
  order,
  compare,
  rows,
  expanded,
  onToggle
}: {
  listName: string;
  order: string[];
  compare: boolean;
  rows: Record<string, RowState>;
  expanded: string | null;
  onToggle: (t: string) => void;
}) {
  const done = order.filter((t) => {
    const s = rows[t]?.status;
    return s === "ok" || s === "error";
  }).length;

  const okViews = order
    .map((t) => ({ t, view: rowView(rows[t] ?? { status: "pending" }) }))
    .filter(
      (x): x is { t: string; view: RowView } =>
        rows[x.t]?.status === "ok" && x.view !== null
    );
  const traded = okViews.filter((x) => x.view.strat.trades > 0);

  const avgReturn =
    okViews.length > 0
      ? okViews.reduce((a, x) => a + x.view.strat.total_return_pct, 0) /
        okViews.length
      : 0;
  const avgWin =
    traded.length > 0
      ? traded.reduce((a, x) => a + x.view.strat.win_rate, 0) / traded.length
      : 0;

  let best: { t: string; v: number } | null = null;
  let worst: { t: string; v: number } | null = null;
  for (const x of okViews) {
    const v = x.view.strat.total_return_pct;
    if (!best || v > best.v) best = { t: x.t, v };
    if (!worst || v < worst.v) worst = { t: x.t, v };
  }

  // Compare mode — which strategy won most often.
  const picks: Record<string, number> = {};
  for (const x of okViews) {
    if (x.view.isCompare && x.view.compare?.best_strategy) {
      const k = x.view.compare.best_strategy;
      picks[k] = (picks[k] ?? 0) + 1;
    }
  }
  const topPick = Object.entries(picks).sort((a, b) => b[1] - a[1])[0];

  const running = done < order.length;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-serif text-xl text-weave-800">{listName} — backtest</h2>
        <p className="text-sm text-weave-500">
          {done} of {order.length} symbols tested
          {compare ? " · best strategy chosen per symbol" : ""}
          {running ? " · still running…" : ` · ${traded.length} produced trades`}
        </p>
      </div>

      {okViews.length > 0 && (
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Average return"
            value={`${avgReturn >= 0 ? "+" : ""}${avgReturn.toFixed(1)}%`}
            tone={avgReturn >= 0 ? "good" : "bad"}
          />
          {compare ? (
            <Metric
              label="Top strategy"
              value={
                topPick
                  ? `${stratName(topPick[0])} · ${topPick[1]}`
                  : "—"
              }
            />
          ) : (
            <Metric
              label="Average win rate"
              value={traded.length > 0 ? `${Math.round(avgWin * 100)}%` : "—"}
            />
          )}
          <Metric
            label="Best"
            value={best ? `${best.t}  ${fmtPct(best.v)}` : "—"}
            tone="good"
          />
          <Metric
            label="Weakest"
            value={worst ? `${worst.t}  ${fmtPct(worst.v)}` : "—"}
            tone="bad"
          />
        </div>
      )}

      <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
              <th className="px-4 py-3">Symbol</th>
              <th className="px-4 py-3">Strategy</th>
              <th className="px-4 py-3 text-right">Trades</th>
              <th className="px-4 py-3 text-right">Win rate</th>
              <th className="px-4 py-3 text-right">Profit factor</th>
              <th className="px-4 py-3 text-right">Return</th>
              <th className="px-4 py-3 text-right">Max drawdown</th>
              <th className="px-4 py-3 text-right">Detail</th>
            </tr>
          </thead>
          <tbody>
            {order.map((t) => (
              <WatchlistRow
                key={t}
                ticker={t}
                state={rows[t] ?? { status: "pending" }}
                open={expanded === t}
                onToggle={() => onToggle(t)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-weave-500">
        Tap any tested row to see its price chart and simulated trades
        {compare ? ", plus how every strategy scored" : ""}. Each run is also
        saved to “Recent backtests” below.
      </p>
    </div>
  );
}

function WatchlistRow({
  ticker,
  state,
  open,
  onToggle
}: {
  ticker: string;
  state: RowState;
  open: boolean;
  onToggle: () => void;
}) {
  if (state.status === "pending") {
    return (
      <tr className="border-b border-weave-50 last:border-0">
        <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
          {ticker}
        </td>
        <td className="px-4 py-2.5 text-weave-400" colSpan={7}>
          Waiting…
        </td>
      </tr>
    );
  }
  if (state.status === "running") {
    return (
      <tr className="border-b border-weave-50 last:border-0">
        <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
          {ticker}
        </td>
        <td className="px-4 py-2.5 text-treasure-700" colSpan={7}>
          Testing…
        </td>
      </tr>
    );
  }

  const view = state.status === "ok" ? rowView(state) : null;
  if (state.status === "error" || !view) {
    return (
      <tr className="border-b border-weave-50 last:border-0">
        <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
          {ticker}
        </td>
        <td
          className="px-4 py-2.5 text-xs text-amber-700"
          colSpan={7}
          title={state.error}
        >
          {state.error ?? "No data"}
        </td>
      </tr>
    );
  }

  const r = view.strat;
  const canExpand = view.candles.length > 1;

  return (
    <>
      <tr
        className={cn(
          "border-b border-weave-50 last:border-0",
          canExpand && "cursor-pointer hover:bg-weave-50/60"
        )}
        onClick={canExpand ? onToggle : undefined}
      >
        <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
          {ticker}
        </td>
        <td className="px-4 py-2.5 text-weave-700" title={view.isCompare ? `${view.stratLabel}: ${stratDesc(view.strat.strategy)}` : stratDesc(view.strat.strategy)}>{view.stratLabel}</td>
        <td className="px-4 py-2.5 text-right font-mono">{r.trades}</td>
        <td
          className="px-4 py-2.5 text-right font-mono"
          title={r.trades === 0 && r.peak_tcs ? "Strongest read during the test — try a threshold below this" : undefined}
        >
          {r.trades > 0
            ? `${Math.round(r.win_rate * 100)}%`
            : r.peak_tcs && r.peak_tcs > 0
              ? <span className="text-weave-400">peak {r.peak_tcs}</span>
              : "—"}
        </td>
        <td className="px-4 py-2.5 text-right font-mono">
          <span title={pfTooltip(r.profit_factor, r.trades)}>{fmtPF(r.profit_factor, r.trades)}</span>
        </td>
        <td
          className={cn(
            "px-4 py-2.5 text-right font-mono font-medium",
            pctClass(r.total_return_pct)
          )}
        >
          {fmtPct(r.total_return_pct)}
        </td>
        <td className="px-4 py-2.5 text-right font-mono text-weave-500">
          -{r.max_drawdown_pct}%
        </td>
        <td className="px-4 py-2.5 text-right">
          {canExpand ? (
            <svg
              className={cn(
                "inline h-4 w-4 text-weave-400 transition-transform",
                open && "rotate-180"
              )}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <span className="text-[11px] text-weave-300">—</span>
          )}
        </td>
      </tr>
      {open && canExpand && (
        <tr className="border-b border-weave-50 last:border-0 bg-weave-50/30">
          <td colSpan={8} className="px-4 py-4">
            {view.isCompare && view.compare && (
              <div className="mb-3 space-y-1.5">
                <p className="text-[10px] uppercase tracking-widest text-weave-500">
                  How every strategy scored on {ticker}
                </p>
                <StrategyBreakdown
                  strategies={view.compare.strategies}
                  best={view.compare.best_strategy}
                />
              </div>
            )}
            {r.trades === 0 && (
              <p className="text-sm text-weave-500 mb-3">
                No trades fired for {ticker} at TCS {r.tcs_threshold}.
                {r.peak_tcs && r.peak_tcs > 0 ? (
                  <>
                    {" "}The strongest read was{" "}
                    <span className="font-medium text-weave-700">TCS {r.peak_tcs}</span>
                    {r.peak_tcs_direction && r.peak_tcs_direction !== "neutral"
                      ? ` (${r.peak_tcs_direction})`
                      : ""}{" "}— try a threshold below that.
                  </>
                ) : (
                  " The line below is the price history that was tested."
                )}
              </p>
            )}
            <div className="space-y-3">
              {view.candles.length > 1 && (
                <BacktestChart candles={view.candles} trades={r.trade_log} />
              )}
              {r.trades > 0 && <TradeTable trades={r.trade_log} compact />}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/* ---------- shared pieces ---------- */

function StrategyBreakdown({
  strategies,
  best,
  selected,
  onSelect
}: {
  strategies: StratResult[];
  best: string | null;
  selected?: string;
  onSelect?: (s: string) => void;
}) {
  const sorted = strategies.slice().sort((a, b) => {
    const at = a.trades > 0 ? 1 : 0;
    const bt = b.trades > 0 ? 1 : 0;
    if (at !== bt) return bt - at;
    return b.total_return_pct - a.total_return_pct;
  });
  return (
    <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
      <table className="w-full text-sm min-w-[480px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
            <th className="px-4 py-3">Strategy</th>
            <th className="px-4 py-3 text-right">Trades</th>
            <th className="px-4 py-3 text-right">Win rate</th>
            <th className="px-4 py-3 text-right">Profit factor</th>
            <th className="px-4 py-3 text-right">Return</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const isBest = s.strategy === best;
            const isSel = s.strategy === selected;
            return (
              <tr
                key={s.strategy}
                onClick={onSelect ? () => onSelect(s.strategy) : undefined}
                className={cn(
                  "border-b border-weave-50 last:border-0",
                  onSelect && "cursor-pointer hover:bg-weave-50/60",
                  isSel && "bg-weave-50"
                )}
              >
                <td className="px-4 py-2.5 text-weave-700" title={stratDesc(s.strategy)}>
                  {stratName(s.strategy)}
                  {isBest && (
                    <span className="ml-2 text-[9px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5">
                      Best
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">{s.trades}</td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {s.trades > 0 ? `${Math.round(s.win_rate * 100)}%` : "—"}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  <span title={pfTooltip(s.profit_factor, s.trades)}>{fmtPF(s.profit_factor, s.trades)}</span>
                </td>
                <td
                  className={cn(
                    "px-4 py-2.5 text-right font-mono font-medium",
                    pctClass(s.total_return_pct)
                  )}
                >
                  {fmtPct(s.total_return_pct)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EmptyRun({
  tcs,
  peak,
  peakDirection
}: {
  tcs: number;
  peak?: number;
  peakDirection?: string;
}) {
  const has = typeof peak === "number" && peak > 0;
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
      No trades fired over this history at TCS {tcs}.
      {has && (
        <>
          {" "}
          The strongest read was{" "}
          <span className="font-medium text-weave-700">TCS {peak}</span>
          {peakDirection && peakDirection !== "neutral"
            ? ` (${peakDirection})`
            : ""}{" "}
          — try a threshold below that to see trades fire.
        </>
      )}
      {!has && " Try a lower threshold or a different symbol."}
    </div>
  );
}

function MetricsGrid({ r, startingCapital = 10000 }: { r: StratResult; startingCapital?: number }) {
  // Dollar P&L computed from compounded total_return_pct. Backtest math
  // is %-based, so this is just a UX layer for "what would $X have
  // become?" — surfaces start/end/net so the result feels real.
  const start = Math.max(0, Number(startingCapital) || 10000);
  const endBalance = start * (1 + (Number(r.total_return_pct) || 0) / 100);
  const netPnl = endBalance - start;
  const usd = (n: number) =>
    n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-weave-100 bg-weave-50/40 p-3 grid grid-cols-3 gap-2 text-sm">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-weave-500">Starting balance</p>
          <p className="font-mono font-medium text-weave-800">{usd(start)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-weave-500">Ending balance</p>
          <p className={cn(
            "font-mono font-medium",
            endBalance >= start ? "text-emerald-700" : "text-red-700"
          )}>
            {usd(endBalance)}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-widest text-weave-500">Net P&L</p>
          <p className={cn(
            "font-mono font-medium",
            netPnl >= 0 ? "text-emerald-700" : "text-red-700"
          )}>
            {netPnl >= 0 ? "+" : ""}{usd(netPnl)}
          </p>
        </div>
      </div>
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-3">
        <Metric
          label="Total return"
          value={fmtPct(r.total_return_pct)}
          tone={r.total_return_pct >= 0 ? "good" : "bad"}
        />
        <Metric label="Win rate" value={`${Math.round(r.win_rate * 100)}%`} />
        <Metric
          label="Profit factor"
          value={fmtPF(r.profit_factor, r.trades)}
          tone={r.profit_factor >= 1 ? "good" : "bad"}
        />
        <Metric
          label="Expectancy / trade"
          value={fmtPct(r.expectancy_pct)}
          tone={r.expectancy_pct >= 0 ? "good" : "bad"}
        />
        <Metric
          label="Max drawdown"
          value={`-${r.max_drawdown_pct}%`}
          tone="bad"
        />
        <Metric label="Wins / losses" value={`${r.wins} / ${r.losses}`} />
      </div>
    </div>
  );
}

function entryTitle(t: Trade) {
  const tcs = t.entry_tcs ? `TCS ${t.entry_tcs}` : "Signal fired";
  const pat = t.entry_pattern
    ? ` · ${t.entry_pattern.replace(/_/g, " ")}`
    : "";
  return `Entry — ${tcs}${pat}`;
}

function exitTitle(t: Trade) {
  return `Exit — ${t.outcome} ${fmtPct(t.pnl_pct)} (closed by ${t.exit_reason})`;
}

function TradeTable({
  trades,
  compact = false
}: {
  trades: Trade[];
  compact?: boolean;
}) {
  const list = trades.slice().reverse();
  const shown = compact ? list.slice(0, 8) : list;
  return (
    <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
      <table className="w-full text-sm min-w-[620px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
            <th className="px-4 py-3 text-right">Entry</th>
            <th className="px-4 py-3">Why it entered</th>
            <th className="px-4 py-3 text-right">Exit</th>
            <th className="px-4 py-3 text-right">P&amp;L</th>
            <th className="px-4 py-3">Outcome</th>
            <th className="px-4 py-3 text-right">Bars held</th>
            <th className="px-4 py-3">Closed by</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t, i) => (
            <tr key={i} className="border-b border-weave-50 last:border-0">
              <td className="px-4 py-2.5 text-right font-mono">
                ${t.entry_price.toFixed(2)}
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
              <td className="px-4 py-2.5 text-right font-mono">
                ${t.exit_price.toFixed(2)}
              </td>
              <td
                className={cn(
                  "px-4 py-2.5 text-right font-mono font-medium",
                  t.pnl_pct >= 0 ? "text-emerald-700" : "text-red-700"
                )}
              >
                {fmtPct(t.pnl_pct)}
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
              <td className="px-4 py-2.5 text-right font-mono text-weave-500">
                {t.bars_held}
              </td>
              <td className="px-4 py-2.5 text-xs text-weave-500">
                {t.exit_reason}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BacktestChart({
  candles,
  trades
}: {
  candles: { c: number }[];
  trades: Trade[];
}) {
  const W = 640;
  const H = 200;
  const padX = 8;
  const padY = 14;
  const closes = candles.map((c) => c.c);
  const n = closes.length;
  const hi = Math.max(...closes);
  const lo = Math.min(...closes);
  const span = hi - lo || 1;
  const x = (i: number) => padX + (n <= 1 ? 0 : i / (n - 1)) * (W - 2 * padX);
  const y = (v: number) => padY + (1 - (v - lo) / span) * (H - 2 * padY);
  const line = closes.map((v, i) => `${x(i)},${y(v)}`).join(" ");

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-3">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="w-full rounded-lg bg-weave-50/40"
        style={{ height: H }}
        role="img"
        aria-label="Backtest price chart with simulated trades"
      >
        <polyline points={line} fill="none" stroke="#6c8e7f" strokeWidth={1.5} />
        {trades.map((t, i) => {
          const ei = Math.max(0, Math.min(n - 1, t.entry_index));
          const xi = Math.max(0, Math.min(n - 1, t.exit_index));
          const win = t.pnl_pct >= 0;
          const color = win ? "#10b981" : "#f87171";
          return (
            <g key={i}>
              <line
                x1={x(ei)}
                x2={x(xi)}
                y1={y(closes[ei])}
                y2={y(closes[xi])}
                stroke={color}
                strokeWidth={1}
                opacity={0.45}
              />
              <circle cx={x(ei)} cy={y(closes[ei])} r={4} fill="#36584d">
                <title>{entryTitle(t)}</title>
              </circle>
              <circle cx={x(xi)} cy={y(closes[xi])} r={4} fill={color}>
                <title>{exitTitle(t)}</title>
              </circle>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-weave-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-weave-600" /> Entry
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-emerald-500" /> Exit — win
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-red-400" /> Exit — loss
        </span>
        <span className="text-weave-400">
          Hover any dot to see why the trade was taken.
        </span>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "neutral"
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad";
}) {
  const toneClass = {
    neutral: "text-weave-800",
    good: "text-emerald-700",
    bad: "text-red-700"
  }[tone];
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5">
      <p className="text-xs uppercase tracking-widest text-weave-500">{label}</p>
      <p className={cn("mt-2 font-serif text-2xl", toneClass)}>{value}</p>
    </div>
  );
}
