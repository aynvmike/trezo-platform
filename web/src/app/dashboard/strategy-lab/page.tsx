import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  getOrSeedDefaultWatchlist,
  seedExampleWatchlists,
  listWatchlistsWithTickers
} from "@/lib/watchlists";
import { Disclosure } from "@/components/ui/disclosure";
import { PatternsBoard } from "@/app/dashboard/patterns/_patterns-board";
import { BacktestRunner } from "@/app/dashboard/backtest/_backtest-runner";
import { SimulationLab } from "@/app/dashboard/simulation/_simulation-lab";
import { StrategyLabTabs } from "./_tabs";

export const dynamic = "force-dynamic";

type Tab = "patterns" | "backtest" | "simulation";

export default async function StrategyLabPage({
  searchParams
}: {
  searchParams: { tab?: string };
}) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/strategy-lab");

  // Shared data: every tab needs the watchlist set in some form.
  const { list, items } = await getOrSeedDefaultWatchlist(user.id);
  await seedExampleWatchlists(user.id);
  const watchlists = await listWatchlistsWithTickers(user.id);
  const symbols = items.map((i) => i.ticker);

  const raw = (searchParams?.tab || "patterns").toLowerCase();
  const tab: Tab =
    raw === "backtest" || raw === "simulation" ? (raw as Tab) : "patterns";

  return (
    <div className="px-4 sm:px-6 py-8 space-y-6 max-w-6xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Strategy Lab
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Score, replay, stress-test
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">
          Three lenses on the same engine. <span className="font-medium">Live
          Patterns</span> shows what the bot sees right now;{" "}
          <span className="font-medium">Backtest</span> replays history for
          one strategy on a ticker or watchlist;{" "}
          <span className="font-medium">Simulation</span> stress-tests every
          strategy across a recent window at once.
        </p>
      </header>

      <StrategyLabTabs />

      {tab === "patterns" && (
        <PatternsTab listName={list.name} symbols={symbols} />
      )}
      {tab === "backtest" && <BacktestTab watchlists={watchlists} />}
      {tab === "simulation" && <SimulationTab watchlists={watchlists} />}
    </div>
  );
}

function PatternsTab({ listName, symbols }: { listName: string; symbols: string[] }) {
  return (
    <section className="space-y-6">
      <p className="beginner-only text-sm text-weave-600 leading-relaxed">
        The bot scans your{" "}
        <span className="font-medium text-weave-800">{listName}</span>{" "}
        watchlist for 12 candlestick patterns across multiple timeframes,
        scoring each ticker from 0 to 1000. Higher means a stronger setup;
        each card shows a snapshot of the price action it scored.
      </p>
      <PatternsBoard symbols={symbols} />
      <Disclosure title="How the score breaks down">
        <div className="space-y-4">
          <div className="space-y-1">
            <p className="font-medium text-weave-800">The outer score (TCS, 0–1000)</p>
            <ul className="list-disc list-inside space-y-0.5">
              <li><span className="font-medium">Technical / pattern (300 max)</span> — the 10 factors below plus a multi-timeframe confluence bonus.</li>
              <li><span className="font-medium">Options environment (250 max)</span> — IV rank in the 30–60 sweet spot gives full credit.</li>
              <li><span className="font-medium">Fundamental / event (200 max)</span> — a news catalyst today.</li>
              <li><span className="font-medium">Risk/reward (150 max)</span> — bracket vs the stop/target.</li>
              <li><span className="font-medium">Market conditions (100 max)</span> — SPY trend + confluence width.</li>
            </ul>
          </div>
          <p className="text-weave-500 text-xs">
            A TCS around 600 means roughly 60% of the available factors
            are firing. A TCS of 700+ means a broad, multi-factor agreement,
            which is why that&apos;s the live-trade threshold.
          </p>
        </div>
      </Disclosure>
    </section>
  );
}

function BacktestTab({ watchlists }: { watchlists: { id: string; name: string; tickers: string[] }[] }) {
  return (
    <section className="space-y-6">
      <p className="beginner-only text-sm text-weave-600 leading-relaxed">
        Replay history through Trezo&apos;s scoring engine to see how a
        strategy would have performed before it ever risks money. Pick a
        watchlist (or a single ticker), strategy, TCS threshold, and
        stop/target — the runner replays the period and gives you trades,
        win rate, profit factor, and total return.
      </p>
      <BacktestRunner watchlists={watchlists} />
    </section>
  );
}

function SimulationTab({ watchlists }: { watchlists: { id: string; name: string; tickers: string[] }[] }) {
  return (
    <section className="space-y-6">
      <p className="beginner-only text-sm text-weave-600 leading-relaxed">
        Stress-test harness. Pick a watchlist, a recent window (5, 7, 14,
        30 days), and a starting account size. Trezo replays the period
        with every strategy scored per stock and stitches together the
        trades that would have fired. When a ticker looks good you can
        promote it straight into Core Winners.
      </p>
      <SimulationLab watchlists={watchlists} />
      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        Each trade is sized as a fixed fraction (25%) of the starting
        equity. Slippage, fees and partial fills aren&apos;t modeled —
        this is for sanity-checking behaviour, not predicting P&amp;L.
      </p>
    </section>
  );
}
