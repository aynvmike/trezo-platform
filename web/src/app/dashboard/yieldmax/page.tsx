import { redirect } from "next/navigation";
import { LayerHero } from "@/components/dashboard/layer-hero";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { YieldMaxTracker } from "@/components/widgets/yieldmax-tracker";
import { getYieldMaxPositions } from "@/lib/positions";
import { LoadError } from "@/components/dashboard/load-error";

export const dynamic = "force-dynamic";

export default async function YieldMaxPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/yieldmax");

  // PAGES-03: null means the read failed — show that, not "no holdings".
  const loaded = await getYieldMaxPositions(user.id);
  const positions = loaded ?? [];

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <LayerHero id={6} openCount={loaded ? positions.length : undefined} action={<Link href="/dashboard/watchlists" className="rounded-md bg-weave-600 px-4 py-2 text-sm font-medium text-treasure-50 hover:bg-weave-700">Add holdings →</Link>} />

      {loaded === null ? (
        <LoadError
          table="user_positions"
          message="Your holdings could not be read. If this persists, migration 0003_user_positions.sql may need applying in Supabase."
        />
      ) : positions.length === 0 ? (
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
