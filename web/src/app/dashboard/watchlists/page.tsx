import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
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
      <PageHeader
        eyebrow="Layer 2 — Watchlists"
        title="Your watchlists"
        subtitle="What the bot scans. Group tickers by theme; pick from the income-ETF library to fund the Dividends layer."
        explainer="The Income ETF picker pours straight into the Dividends layer. Ethical filters apply on every add — settings live under Filters."
        action={<NewWatchlistButton />}
      />

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
