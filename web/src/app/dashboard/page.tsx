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

  // Source of truth: Alpaca equity when connected, profile fallback otherwise
  // (Mike 2026-05-29 — avoid the phantom-portfolio sizing bug).
  const alpacaActive = !!(alpaca?.configured && alpaca?.account);
  const liveEquity = alpacaActive ? Number(alpaca!.account!.equity) : null;
  const liveCash = alpacaActive ? Number(alpaca!.account!.cash) : null;

  const stockCapital = liveEquity ?? Number(profile?.stock_capital_usd ?? 0);
  const cryptoHoldings = paperAcct?.crypto_balance_usd
    ? Number(paperAcct.crypto_balance_usd)
    : Number(profile?.crypto_capital_usd ?? 0);
  const dailyTarget = Number(profile?.daily_profit_target_usd ?? 0);

  return (
    <div className="px-4 sm:px-8 py-8 sm:py-10 space-y-10 max-w-6xl">
      {/* ---- Hero ------------------------------------------------------- */}
      <header className="relative">
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-treasure-600">
          Overview
        </p>
        <h1 className="mt-2 font-serif text-3xl sm:text-4xl tracking-tight text-weave-800">
          Welcome back, {profile?.display_name ?? "friend"}.
        </h1>
        <p className="beginner-only mt-3 max-w-2xl text-sm text-weave-600 leading-relaxed">
          Live data below. Bots and strategies come online layer by layer.
        </p>
        <div className="mt-6 h-px w-full bg-gradient-to-r from-treasure-500/50 via-weave-200 to-transparent" />
      </header>

      {/* ---- KPI band -------------------------------------------------- */}
      <section className="space-y-2">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <KPI
            label={alpacaActive ? "Stock capital · Alpaca live" : "Stock capital"}
            value={stockCapital}
            live={alpacaActive}
          />
          <KPI label="Crypto holdings" value={cryptoHoldings} accent="treasure" />
          <KPI label="Daily target" value={dailyTarget} accent="weave" />
        </div>
        {alpacaActive ? (
          <p className="text-[11px] text-weave-500 leading-relaxed">
            Stock capital reads from your Alpaca account equity
            (<span className="font-mono tabular-nums">${liveEquity?.toLocaleString()}</span>{" "}
            · cash <span className="font-mono tabular-nums">${liveCash?.toLocaleString()}</span>).
            Values sum across brokerages as more are wired.
          </p>
        ) : (
          <p className="text-[11px] text-weave-500 leading-relaxed">
            Showing onboarding values. Connect Alpaca on{" "}
            <Link href="/dashboard/settings/connections" className="text-treasure-600 underline underline-offset-2">
              Connections
            </Link>{" "}
            and these tiles reflect your real account.
          </p>
        )}
      </section>

      <PerformanceSnapshot userId={user.id} />

      {/* ---- Layers + activity ---------------------------------------- */}
      <section className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-10 min-w-0">
          <div>
            <SectionHead eyebrow="Layer 1" title="Live crypto" href="/dashboard/crypto" cta="Open" />
            <CryptoCards />
          </div>
          <div>
            <SectionHead eyebrow="Layer 2" title="Watchlist preview" href="/dashboard/stocks" cta="Open" />
            <StockQuotes symbols={["AMD", "INTC", "CZR", "WMT", "AMSC"]} />
          </div>
        </div>

        <aside className="min-w-0">
          <SectionHead eyebrow="Live feed" title="Activity" href="/dashboard/agents" cta="Manage agents" />
          <div className="rounded-2xl border bg-white/40 p-1.5 shadow-sm">
            <ActivityFeed limit={30} refreshSec={5} maxHeight="620px" />
          </div>
        </aside>
      </section>
    </div>
  );
}

/* ---- section header: gold eyebrow + serif title + hairline rule ------ */
function SectionHead({
  eyebrow,
  title,
  href,
  cta
}: {
  eyebrow: string;
  title: string;
  href: string;
  cta: string;
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-3 border-b border-weave-200/70 pb-2.5">
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-treasure-600">
          {eyebrow}
        </p>
        <h2 className="mt-0.5 font-serif text-xl text-weave-800 tracking-tight">{title}</h2>
      </div>
      <Link
        href={href}
        className="shrink-0 text-xs font-medium text-weave-500 transition-colors hover:text-weave-800"
      >
        {cta} →
      </Link>
    </div>
  );
}

/* ---- KPI tile: lifted obsidian card, sharp top accent, serif value --- */
function KPI({
  label,
  value,
  live,
  accent = "treasure"
}: {
  label: string;
  value: number;
  live?: boolean;
  accent?: "treasure" | "weave" | "emerald";
}) {
  const bar = live
    ? "via-emerald-500/70"
    : accent === "weave"
      ? "via-weave-500/60"
      : "via-treasure-500/60";
  const dot = live ? "bg-emerald-500" : accent === "weave" ? "bg-weave-500" : "bg-treasure-500";
  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-2xl border p-5 shadow-sm transition-shadow hover:shadow-md",
        "bg-gradient-to-b from-white to-weave-50/40",
        live ? "border-emerald-300/60" : "border-weave-200/70"
      )}
    >
      {/* sharp top hairline — the obsidian edge */}
      <span className={cn("absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent to-transparent", bar)} />
      <div className="flex items-center gap-2">
        <span className={cn("h-1.5 w-1.5 rounded-full", dot, live && "animate-pulse")} />
        <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-weave-500">{label}</p>
        {live && (
          <span className="ml-auto rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-emerald-800">
            Live
          </span>
        )}
      </div>
      <p className="mt-3 font-serif text-[1.7rem] leading-none text-weave-800 tabular-nums">
        ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </p>
    </div>
  );
}
