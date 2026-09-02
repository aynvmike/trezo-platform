import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { createClient } from "@/lib/supabase/server";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";
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
import { MarketScanPanel } from "@/app/dashboard/simulation/_market-scan";

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

  // Live Patterns follows the PORTFOLIO (Mike 2026-07-14): chart what the
  // book actually holds right now; fall back to the watchlist when flat.
  // rv:web-pages sweep: both tables are keyed by BOOK (0047); "what the
  // book holds" means every book the person owns. Display-only here: a
  // failed resolution simply falls back to the watchlist below.
  const booksLoad = await getOwnerBookKeys(supabase, user.id);
  const keys = bookQueryKeys(booksLoad.data);
  const { data: openPos } = await supabase
    .from("paper_positions")
    .select("ticker, asset_type")
    .in("user_id", keys)
    .eq("status", "open");
  const { data: openOpt } = await supabase
    .from("options_positions")
    .select("underlying")
    .in("user_id", keys)
    .eq("status", "open");
  const held = Array.from(
    new Set([
      ...(openPos ?? [])
        .filter((p) => p.asset_type !== "forex")
        .map((p) => String(p.ticker).toUpperCase()),
      ...(openOpt ?? []).map((o) => String(o.underlying).toUpperCase())
    ])
  );

  const raw = (searchParams?.tab || "patterns").toLowerCase();
  const tab: Tab =
    raw === "backtest" || raw === "simulation" ? (raw as Tab) : "patterns";

  return (
    <div className="px-4 sm:px-6 py-8 space-y-6 max-w-6xl">
      <PageHeader
        eyebrow="Strategy Lab"
        title="Score, replay, stress-test"
        subtitle="Three lenses on the same engine — Live Patterns shows what the bot sees now; Backtest replays history for one strategy; Simulation stress-tests every strategy across a recent window at once."
      />

      <StrategyLabTabs />

      {tab === "patterns" && (
        <PatternsTab listName={list.name} symbols={symbols} held={held} />
      )}
      {tab === "backtest" && <BacktestTab watchlists={watchlists} />}
      {tab === "simulation" && <SimulationTab watchlists={watchlists} />}
    </div>
  );
}

function PatternsTab({ listName, symbols, held }: { listName: string; symbols: string[]; held: string[] }) {
  const showHeld = held.length > 0;
  const show = showHeld ? held : symbols;
  return (
    <section className="space-y-6">
      <p className="beginner-only text-sm text-weave-600 leading-relaxed">
        {showHeld ? (
          <>
            Showing the{" "}
            <span className="font-medium text-weave-800">
              {held.length} position{held.length === 1 ? "" : "s"} the
              portfolio holds right now
            </span>{" "}
            — the bot re-scores 12 candlestick patterns across multiple
            timeframes on every name it is actually in (0 to 100). When the
            book is flat this falls back to your {listName} watchlist.
          </>
        ) : (
          <>
            The portfolio is flat, so the bot scans your{" "}
            <span className="font-medium text-weave-800">{listName}</span>{" "}
            watchlist for 12 candlestick patterns across multiple timeframes,
            scoring each ticker from 0 to 100.
          </>
        )}
      </p>
      <PatternsBoard symbols={show} />
      <Disclosure title="How the score breaks down">
        <div className="space-y-4">
          <div className="space-y-1">
            <p className="font-medium text-weave-800">The outer score (TCS, 0–100)</p>
            <ul className="list-disc list-inside space-y-0.5">
              <li><span className="font-medium">Technical / pattern (30 max)</span> — the 10 factors below plus a multi-timeframe confluence bonus.</li>
              <li><span className="font-medium">Options environment (25 max)</span> — IV rank in the 30–60 sweet spot gives full credit.</li>
              <li><span className="font-medium">Fundamental / event (20 max)</span> — a news catalyst today.</li>
              <li><span className="font-medium">Risk/reward (15 max)</span> — bracket vs the stop/target.</li>
              <li><span className="font-medium">Market conditions (10 max)</span> — SPY trend + confluence width.</li>
            </ul>
          </div>
          <p className="text-weave-500 text-xs">
            A TCS around 60 means roughly 60% of the available factors are
            firing; 70+ is broad multi-factor agreement. The live-trade bar
            is your Bot Tuning threshold plus any regime bump.
          </p>
        </div>
      </Disclosure>
    </section>
  );
}

function BacktestTab({ watchlists }: { watchlists: { id: string; name: string; is_default: boolean; tickers: { ticker: string; asset_type: string }[] }[] }) {
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

function SimulationTab({ watchlists }: { watchlists: { id: string; name: string; is_default: boolean; tickers: { ticker: string; asset_type: string }[] }[] }) {
  return (
    <section className="space-y-6">
      <p className="beginner-only text-sm text-weave-600 leading-relaxed">
        Stress-test harness — and the home for testing how the agents adapt
        at different account sizes ($1k, $5k, $10k, $25k, $100k), as a
        simulation that never touches your live paper account. Pick a
        watchlist, a recent window (5, 7, 14, 30 days), and a starting
        account size. Trezo replays the period
        with every strategy scored per stock and stitches together the
        trades that would have fired. When a ticker looks good you can
        promote it straight into Core Winners.
      </p>
      <MarketScanPanel />
      <SimulationLab watchlists={watchlists} />
      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        Each trade is sized as a fixed fraction (25%) of the starting
        equity. Slippage, fees and partial fills aren&apos;t modeled —
        this is for sanity-checking behaviour, not predicting P&amp;L.
      </p>
    </section>
  );
}
