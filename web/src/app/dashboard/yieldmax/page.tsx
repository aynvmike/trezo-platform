import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { YieldMaxTracker } from "@/components/widgets/yieldmax-tracker";
import { getYieldMaxPositions } from "@/lib/positions";

export const dynamic = "force-dynamic";

export default async function YieldMaxPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/yieldmax");

  const positions = await getYieldMaxPositions(user.id);

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
            Layer 6 — Dividends
          </p>
          <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
            Your dividend holdings
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">Your dividend holdings — live prices and DRIP tracking. Add from Watchlists; manage shares and DRIP on each card.</p>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
            This page shows the dividend income holdings you actually own —
            what they are worth and what they pay. Add new holdings from{" "}
            <Link
              href="/dashboard/watchlists"
              className="underline hover:text-weave-800"
            >
              Watchlists
            </Link>{" "}
            (the Income ETF picker lives there now). With DRIP on, each
            distribution reinvests and the position compounds.
          </p>
        </div>
        <Link
          href="/dashboard/watchlists"
          className="rounded-md bg-weave-600 px-4 py-2 text-sm font-medium text-treasure-50 hover:bg-weave-700"
        >
          Add holdings →
        </Link>
      </header>

      {positions.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-8 text-center space-y-3">
          <p className="font-medium text-weave-800">
            No dividend holdings yet.
          </p>
          <p className="text-sm text-weave-600 leading-relaxed max-w-md mx-auto">
            Head to{" "}
            <Link
              href="/dashboard/watchlists"
              className="underline hover:text-weave-800"
            >
              Watchlists
            </Link>{" "}
            and pick from the Income ETF library — YieldMax, REX / NEOS,
            JEPI / JEPQ, Global X covered calls, iShares, Schwab, high-yield
            bond, REITs &amp; MLPs — or add any dividend-paying ticker. The
            market data feed will fill in the company name automatically.
          </p>
          <p className="text-[11px] text-weave-400">
            If the page errors instead, the migration{" "}
            <code className="text-xs">0003_user_positions.sql</code> may
            need applying in Supabase.
          </p>
        </div>
      ) : (
        <YieldMaxTracker
          positions={positions.map((p) => ({
            id: p.id,
            ticker: p.ticker,
            shares: Number(p.shares),
            cumulative_dist: Number(p.cumulative_dist),
            drip_enabled: p.drip_enabled,
            dist_yield_pct: Number(p.dist_yield_pct),
            name: p.notes ?? null
          }))}
        />
      )}
    </div>
  );
}
