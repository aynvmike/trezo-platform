import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getOrSeedDefaultWatchlist } from "@/lib/watchlists";
import { StockQuotes } from "@/components/widgets/stock-quotes";

export const dynamic = "force-dynamic";

export default async function StocksPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/stocks");

  const { list, items } = await getOrSeedDefaultWatchlist(user.id);
  const symbols = items.map((i) => i.ticker);

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
            Layer 2 — Stock Bot (STMS)
          </p>
          <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
            {list.name}
          </h1>
          <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
            Live quotes from Finnhub. This view follows your default watchlist —
            edit it from{" "}
            <Link
              href="/dashboard/watchlists"
              className="underline hover:text-weave-800"
            >
              Watchlists
            </Link>
            . The Small Trades Momentum Strategy goes live in Phase 6.
          </p>
        </div>
        <Link
          href={`/dashboard/watchlists/${list.id}`}
          className="text-sm text-weave-600 hover:underline"
        >
          Edit watchlist →
        </Link>
      </header>

      {symbols.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-600">
          Your default watchlist is empty.{" "}
          <Link
            href={`/dashboard/watchlists/${list.id}`}
            className="underline hover:text-weave-800"
          >
            Add some tickers
          </Link>{" "}
          to start seeing quotes here.
        </div>
      ) : (
        <StockQuotes symbols={symbols} />
      )}

      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6">
        <p className="text-sm text-weave-600 leading-relaxed">
          <span className="font-medium text-weave-800">Note:</span> Finnhub free
          tier returns <code className="text-xs">$0.00</code> outside regular
          trading hours (9:30 AM – 4:00 PM ET, weekdays). If you&apos;re seeing
          zeros, that&apos;s why.
        </p>
      </div>
    </div>
  );
}
