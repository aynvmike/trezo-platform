import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { CryptoCards } from "@/components/widgets/crypto-card";
import { StockQuotes } from "@/components/widgets/stock-quotes";
import { ActivityFeed } from "@/components/dashboard/activity-feed";
import { PerformanceSnapshot } from "@/components/dashboard/performance-snapshot";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard");

  const [{ data: profile }, alpaca, { data: paperAcct }] = await Promise.all([
    supabase.from("profiles").select("*").eq("user_id", user.id).maybeSingle(),
    fetchAlpacaSnapshot(),
    supabase.from("paper_accounts").select("crypto_balance_usd").eq("user_id", user.id).maybeSingle()
  ]);

  // Mike feedback 2026-05-29: the KPIs were reading hardcoded profile
  // fields ($15k stock capital, $10k crypto), which mismatched the real
  // Alpaca account (~$8.5k equity). That mismatch is dangerous - the
  // account-size-aware posture logic was sizing trades for a phantom
  // $25k portfolio. Source of truth is now: Alpaca equity when
  // connected, profile fallback otherwise. Multiple brokerage accounts
  // will be summed below as soon as Trezo wires a second broker.
  const alpacaActive = !!(alpaca?.configured && alpaca?.account);
  const liveEquity = alpacaActive ? Number(alpaca!.account!.equity) : null;
  const liveCash = alpacaActive ? Number(alpaca!.account!.cash) : null;

  // Alpaca paper trading is stock-only, so all live equity counts toward
  // stocks. Crypto holdings come from the internal paper account (the
  // crypto SCALP/SWING/DCA engine runs on the internal ledger, not
  // Alpaca). Falls back to the profile defaults when neither is wired.
  const stockCapital = liveEquity ?? Number(profile?.stock_capital_usd ?? 0);
  const cryptoHoldings = paperAcct?.crypto_balance_usd
    ? Number(paperAcct.crypto_balance_usd)
    : Number(profile?.crypto_capital_usd ?? 0);
  const dailyTarget = Number(profile?.daily_profit_target_usd ?? 0);

  return (
    <div className="px-4 sm:px-6 py-8 space-y-10 max-w-6xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Overview
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Welcome back, {profile?.display_name ?? "friend"}.
        </h1>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          Live data below. Bots and strategies come online layer by layer.
        </p>
      </header>

      <section className="space-y-1">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <KPI
            label={alpacaActive ? "Stock capital - Alpaca live" : "Stock capital"}
            value={stockCapital}
            live={alpacaActive}
          />
          <KPI label="Crypto holdings" value={cryptoHoldings} />
          <KPI label="Daily target" value={dailyTarget} />
        </div>
        {alpacaActive ? (
          <p className="text-[11px] text-weave-500 leading-relaxed">
            Stock capital reads from your Alpaca account equity
            (<span className="font-mono">${liveEquity?.toLocaleString()}</span>{" "}
            · cash <span className="font-mono">${liveCash?.toLocaleString()}</span>).
            When multiple brokerages are wired, the values sum across all
            connected accounts.
          </p>
        ) : (
          <p className="text-[11px] text-weave-500 leading-relaxed">
            Showing onboarding values. Connect Alpaca on{" "}
            <Link href="/dashboard/settings/connections" className="underline">
              Connections
            </Link>{" "}
            and these tiles will reflect your real account.
          </p>
        )}
      </section>

      <PerformanceSnapshot userId={user.id} />

      <section className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-10 min-w-0">
          <div>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="font-serif text-xl text-weave-800">Live crypto</h2>
              <Link href="/dashboard/crypto" className="text-sm text-weave-600 hover:underline">
                Open Layer 1 -&gt;
              </Link>
            </div>
            <CryptoCards />
          </div>

          <div>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="font-serif text-xl text-weave-800">Watchlist preview</h2>
              <Link href="/dashboard/stocks" className="text-sm text-weave-600 hover:underline">
                Open Layer 2 -&gt;
              </Link>
            </div>
            <StockQuotes symbols={["AMD", "INTC", "CZR", "WMT", "AMSC"]} />
          </div>
        </div>

        <aside>
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="font-serif text-xl text-weave-800">Activity</h2>
            <Link href="/dashboard/agents" className="text-sm text-weave-600 hover:underline">
              Manage agents -&gt;
            </Link>
          </div>
          <ActivityFeed limit={30} refreshSec={5} maxHeight="640px" />
        </aside>
      </section>
    </div>
  );
}

function KPI({
  label,
  value,
  live
}: {
  label: string;
  value: number;
  live?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-5",
        live ? "border-emerald-200 bg-emerald-50/40" : "border-weave-100 bg-white"
      )}
    >
      <div className="flex items-baseline gap-2">
        <p className="text-xs uppercase tracking-widest text-weave-500">{label}</p>
        {live && (
          <span className="text-[9px] uppercase tracking-widest rounded-full px-1.5 py-0.5 bg-emerald-100 text-emerald-800">
            LIVE
          </span>
        )}
      </div>
      <p className="mt-2 font-serif text-2xl text-weave-800">
        ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </p>
    </div>
  );
}
