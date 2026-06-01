import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { listWatchlists, getOrSeedDefaultWatchlist, seedExampleWatchlists, listWatchlistsWithTickers } from "@/lib/watchlists";
import {
  INCOME_ETF_LIBRARY,
  getYieldMaxPositions
} from "@/lib/positions";
import { addHolding } from "@/app/dashboard/yieldmax/_actions";
import { NewWatchlistButton } from "./_new-watchlist-button";
import { WatchlistGrid } from "./_watchlist-grid";
import { GlobalTickerAdd } from "@/components/dashboard/global-ticker-add";

export const dynamic = "force-dynamic";

export default async function WatchlistsIndex() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/watchlists");

  // Make sure the default list exists (also seeds Core Winners on first call)
  await getOrSeedDefaultWatchlist(user.id);
  await seedExampleWatchlists(user.id);

  const lists = await listWatchlists(user.id);
  const heldYieldMax = await getYieldMaxPositions(user.id);

  // Pre-fetch tickers for every list so the inline expand renders
  // instantly when a card is opened. Mike 2026-06-01.
  const listsWithTickers = await listWatchlistsWithTickers(user.id);
  const tickersById = new Map(
    listsWithTickers.map((l) => [l.id, l.tickers])
  );

  // Build chips for the global Add Ticker form. Default asset type is
  // crypto for any list whose name signals crypto (GENIUS Act, Crypto
  // Core, etc.); everything else defaults to stock.
  const chips = lists.map((l) => {
    const n = l.name.toLowerCase();
    const isCrypto =
      n.includes("crypto") || n.includes("genius act");
    return {
      id: l.id,
      name: l.name,
      default_asset_type: (isCrypto ? "crypto" : "stock") as
        | "stock"
        | "crypto",
    };
  });

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
            Layer 2 — Watchlists
          </p>
          <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
            Your watchlists
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">What the bot scans. Group tickers by theme; pick from the income-ETF library to fund the Dividends layer.</p>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
            Group tickers however suits the way you trade. The Income ETF
            picker below pours straight into the{" "}
            <Link
              href="/dashboard/yieldmax"
              className="underline hover:text-weave-800"
            >
              Dividends layer
            </Link>
            . Ethical filters apply on every add - settings live under{" "}
            <Link
              href="/dashboard/settings/filters"
              className="underline hover:text-weave-800"
            >
              Filters
            </Link>
            .
          </p>
        </div>
        <NewWatchlistButton />
      </header>

      <GlobalTickerAdd chips={chips} />

      <WatchlistGrid
        lists={lists.map((l) => ({
          id: l.id,
          name: l.name,
          is_default: Boolean(l.is_default),
          item_count: l.item_count,
          tickers: tickersById.get(l.id) ?? []
        }))}
        library={INCOME_ETF_LIBRARY}
        heldTickers={heldYieldMax.map((p) => p.ticker)}
        addHolding={addHolding}
      />
    </div>
  );
}
