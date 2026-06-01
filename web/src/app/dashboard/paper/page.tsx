import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

import { AccountSizeSim } from "@/components/dashboard/account-size-sim";
import { ScannerPulse } from "@/components/dashboard/scanner-pulse";
import { AlpacaSnapshot } from "@/components/dashboard/alpaca-snapshot";
import { BotSettingsPanel } from "@/components/dashboard/bot-settings-panel";
import { RunScannerButton } from "@/components/dashboard/run-scanner-button";
import { TodaysExecutionFeed } from "@/components/dashboard/todays-execution-feed";
import { StrategyWindows } from "@/components/dashboard/strategy-windows";
import { VetoReasonsPanel } from "@/components/dashboard/veto-reasons-panel";
import { DiagnoseNowButton } from "@/components/dashboard/diagnose-now-button";
import { ManualTradeButton } from "@/components/dashboard/manual-trade-button";
import { SignalTracePanel } from "@/components/dashboard/signal-trace-panel";
import { Disclosure } from "@/components/ui/disclosure";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";
import { MarketSidePanelServer } from "@/components/dashboard/market-side-panel-server";
import { StocksReconcileButton } from "@/components/dashboard/stocks-reconcile-button";
import { TradingModeBanner } from "@/components/dashboard/trading-mode-banner";
import { CyclesPanel } from "@/components/dashboard/cycles-panel";
import { ExitAdvisorAlerts } from "@/components/dashboard/exit-advisor-alerts";
import { CapitalPressurePanel } from "@/components/dashboard/capital-pressure-panel";
import { Iso20022CryptoPanel } from "@/components/dashboard/iso20022-crypto-panel";
import { requestClose } from "./_actions";

export const dynamic = "force-dynamic";

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
  });
}

function prettyStrategy(s: string | null | undefined): string {
  const v = String(s ?? "system");
  if (v === "default" || v === "system") return "system";
  return v.replace(/_/g, " ");
}

type Position = {
  id: string;
  ticker: string;
  asset_type: string;
  side: string;
  quantity: number;
  entry_price: number;
  stop_price: number | null;
  target_price: number | null;
  status: string;
  exit_price: number | null;
  realized_pnl_usd: number | null;
  strategy: string | null;
  entry_at: string;
  exit_at: string | null;
};

export default async function PaperPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/paper");

  // Auto-trade toggle for the banner.
  const { data: botSettingsRow } = await supabase
    .from("bot_settings")
    .select("auto_trade_enabled")
    .eq("user_id", user.id)
    .maybeSingle();
  const autoTradeEnabled =
    botSettingsRow?.auto_trade_enabled !== false;

  // Account + positions + recent trades in parallel.
  const [accountRes, openRes, closedRes, alpaca] = await Promise.all([
    supabase
      .from("paper_accounts")
      .select("*")
      .eq("user_id", user.id)
      .maybeSingle(),
    supabase
      .from("paper_positions")
      .select("*")
      .eq("user_id", user.id)
      .eq("status", "open")
      .order("entry_at", { ascending: false }),
    supabase
      .from("paper_positions")
      .select("*")
      .eq("user_id", user.id)
      .neq("status", "open")
      .order("exit_at", { ascending: false })
      .limit(20),
    fetchAlpacaSnapshot(),
  ]);

  const account = accountRes.data;
  const openPositions = (openRes.data ?? []) as Position[];
  const closedPositions = (closedRes.data ?? []) as Position[];

  // Alpaca live override when configured.
  const alpacaActive = !!(alpaca?.configured && alpaca?.account);
  const a = alpaca?.account;
  const displayCash = alpacaActive
    ? Number(a!.cash)
    : Number(account?.current_cash_usd ?? 0);
  const displayEquity = alpacaActive
    ? Number(a!.equity)
    : Number(account?.current_cash_usd ?? 0) +
      Number(account?.vault_balance_usd ?? 0);

  // Daily P&L is REALIZED ONLY - closed trades, never broker drift.
  const todayRealized = Number(account?.today_realized_pnl_usd ?? 0);
  const ytdRealized = Number(account?.ytd_realized_pnl_usd ?? 0);
  const vaultBalance = Number(account?.vault_balance_usd ?? 0);

  // Profit-lock + loss-limit thresholds (from profile, fallback defaults).
  const { data: profile } = await supabase
    .from("profiles")
    .select("daily_profit_lock_usd, daily_loss_limit_usd")
    .eq("user_id", user.id)
    .maybeSingle();
  const profitLockTarget = Number(profile?.daily_profit_lock_usd ?? 500);
  const lossLimitTarget = Number(profile?.daily_loss_limit_usd ?? 100);

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      {/* Mode banner - first thing the user sees. */}
      <TradingModeBanner autoTradeEnabled={autoTradeEnabled} />

      {/* Exit Advisor + Capital pressure - eye-catchers when action is needed. */}
      <ExitAdvisorAlerts />
      <CapitalPressurePanel userId={user.id} />

      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Trading
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Your trading account
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">
          Every approved signal lands here; every position closes here.
          The mode banner above tells you whether trades route to your
          Alpaca paper account (safe default) or to live brokerage
          (gated behind the Phase 10b checklist).
        </p>
      </header>

      <Disclosure title="Going live — checklist">
        <div className="space-y-2 text-sm text-weave-700 leading-relaxed">
          <p>
            Trezo stays in PAPER mode by default. To flip the banner
            to LIVE: set TRADING_MODE=live in agents/.env AND restart
            the agents service. The live executor stays gated until
            Phase 10b ships - until then every trade still routes
            paper even when "LIVE (requested)" is the mode.
          </p>
          <p>
            For the live executor to actually fire orders, the user
            must also flip Auto-trade ON in Bot Tuning AND have a
            broker connection with options approval (for the Wheel)
            or buying power (for stocks).
          </p>
        </div>
      </Disclosure>

      {/* Quick actions */}
      <section className="grid gap-3 sm:grid-cols-4">
        <QuickAction
          href="/dashboard/settings/bot"
          label="Bot Tuning"
          desc="Risk, confidence threshold, which strategies run"
        />
        <QuickAction
          href="/dashboard/agents"
          label="Agents"
          desc="Turn agents on or off, or run one now"
        />
        <QuickAction
          href="/dashboard/strategy-lab"
          label="Backtest"
          desc="Test a strategy on history before it trades"
        />
        <QuickAction
          href="/dashboard/watchlists"
          label="Watchlists"
          desc="Edit what the bot scans"
        />
      </section>

      {/* Headline KPIs */}
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KPI
          label="Cash (buying power)"
          value={fmtUsd(displayCash)}
          tone="treasure"
        />
        <KPI
          label="Vault (locked)"
          value={fmtUsd(vaultBalance)}
        />
        <KPI
          label="Today's P&L · realized"
          value={fmtUsd(todayRealized)}
          tone={
            todayRealized > 0 ? "good" : todayRealized < 0 ? "bad" : "neutral"
          }
        />
        <KPI
          label="YTD P&L"
          value={fmtUsd(ytdRealized)}
          tone={
            ytdRealized > 0 ? "good" : ytdRealized < 0 ? "bad" : "neutral"
          }
        />
      </section>
      <p className="text-[11px] text-weave-500 -mt-4 leading-relaxed">
        Today&apos;s P&amp;L is{" "}
        <span className="font-medium">realized only</span> — the sum of
        trades that actually closed today. The open positions card below
        shows the live mark-to-market drift that does NOT drive the loss
        kill-switch.
      </p>

      {/* Profit-lock + loss-limit rails */}
      <section className="grid gap-3 sm:grid-cols-2">
        <RailCard
          title="Daily Profit Lock"
          used={Math.max(0, todayRealized)}
          target={profitLockTarget}
          desc={`When today's realized P&L reaches ${fmtUsd(profitLockTarget)}, that amount auto-locks into your vault. Source: closed trades only (open positions never trip the lock).`}
        />
        <RailCard
          title="Daily Loss Limit"
          used={Math.abs(Math.min(0, todayRealized))}
          target={lossLimitTarget}
          desc={`If today's realized loss reaches ${fmtUsd(lossLimitTarget)}, Risk Manager vetoes all new signals for the rest of the day.`}
        />
      </section>

      {/* Alpaca account snapshot */}
      <AlpacaSnapshot />

      {/* Market context */}
      <MarketSidePanelServer />

      <CyclesPanel userId={user.id} />

      <Iso20022CryptoPanel />

      <StrategyWindows />

      {/* Scanner + diagnostic controls */}
      <section className="grid gap-3 sm:grid-cols-3">
        <RunScannerButton
          name="stocks"
          label="Run stock scan now"
          hint="Runs the active stock strategy on your watchlist immediately."
        />
        <DiagnoseNowButton />
        <StocksReconcileButton />
      </section>

      <ManualTradeButton />

      <ScannerPulse userId={user.id} />
      <VetoReasonsPanel userId={user.id} />
      <SignalTracePanel userId={user.id} />

      {/* Today's execution feed */}
      <Disclosure title="Today's execution feed (diagnostic - click to expand)">
        <TodaysExecutionFeed userId={user.id} />
      </Disclosure>

      {/* Bot settings in-force snapshot */}
      <BotSettingsPanel userId={user.id} />

      <AccountSizeSim brokerConnected={Boolean(alpaca?.configured)} />

      {/* Open positions */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Open positions{" "}
          <span className="text-sm text-weave-500">
            ({openPositions.length})
          </span>
        </h2>
        {openPositions.length === 0 ? (
          <EmptyCard>
            No open positions. When an approved signal fires, it appears
            here.
          </EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[760px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3 text-right">Qty</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Stop</th>
                  <th className="px-4 py-3 text-right">Target</th>
                  <th className="px-4 py-3">Strategy</th>
                  <th className="px-4 py-3 text-right">Close</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p) => (
                  <tr
                    key={p.id}
                    className="border-b border-weave-50 last:border-0"
                  >
                    <td className="px-4 py-3 font-mono font-medium text-weave-800">
                      {p.ticker}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                          p.side === "long"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-amber-100 text-amber-800"
                        )}
                      >
                        {p.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {Number(p.quantity).toFixed(
                        p.asset_type === "crypto" ? 4 : 0
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {fmtUsd(p.entry_price)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-weave-500">
                      {p.stop_price ? fmtUsd(p.stop_price) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-weave-500">
                      {p.target_price ? fmtUsd(p.target_price) : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-weave-600">
                      {prettyStrategy(p.strategy)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <form action={requestClose}>
                        <input
                          type="hidden"
                          name="position_id"
                          value={p.id}
                        />
                        <button
                          type="submit"
                          className="text-xs rounded border border-weave-200 px-2 py-1 text-weave-700 hover:bg-weave-50"
                        >
                          Close now
                        </button>
                      </form>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Recent trades */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Recent trades{" "}
          <span className="text-sm text-weave-500">
            ({closedPositions.length})
          </span>
        </h2>
        {closedPositions.length === 0 ? (
          <EmptyCard>No closed trades yet today.</EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Exit</th>
                  <th className="px-4 py-3 text-right">P&L</th>
                  <th className="px-4 py-3">Closed by</th>
                </tr>
              </thead>
              <tbody>
                {closedPositions.map((p) => {
                  const pnl = Number(p.realized_pnl_usd ?? 0);
                  return (
                    <tr
                      key={p.id}
                      className="border-b border-weave-50 last:border-0"
                    >
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {p.ticker}
                      </td>
                      <td className="px-4 py-3 text-weave-600">{p.side}</td>
                      <td className="px-4 py-3 text-right font-mono">
                        {fmtUsd(p.entry_price)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {fmtUsd(p.exit_price)}
                      </td>
                      <td
                        className={cn(
                          "px-4 py-3 text-right font-mono",
                          pnl > 0 && "text-emerald-700",
                          pnl < 0 && "text-red-600"
                        )}
                      >
                        {fmtUsd(pnl)}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {String(p.status).replace("closed_", "")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-[11px] text-weave-500 italic">
        Want a comprehensive view of today&apos;s activity?{" "}
        <Link
          href="/dashboard/agents"
          className="underline hover:text-weave-800"
        >
          Open the Agents page →
        </Link>
      </p>
    </div>
  );
}

function QuickAction({
  href,
  label,
  desc,
}: {
  href: string;
  label: string;
  desc: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-xl border border-weave-100 bg-white p-4 transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <p className="font-medium text-weave-800">{label}</p>
      <p className="mt-1 text-xs text-weave-500 leading-relaxed">{desc}</p>
      <span className="mt-2 inline-block text-xs text-weave-600">Open →</span>
    </Link>
  );
}

function KPI({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad" | "treasure";
}) {
  const toneClass = {
    neutral: "text-weave-800",
    good: "text-emerald-700",
    bad: "text-red-700",
    treasure: "text-treasure-700",
  }[tone];
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">
        {label}
      </p>
      <p className={cn("mt-1 font-mono text-lg font-medium", toneClass)}>
        {value}
      </p>
    </div>
  );
}

function RailCard({
  title,
  used,
  target,
  desc,
}: {
  title: string;
  used: number;
  target: number;
  desc: string;
}) {
  const pct = target > 0 ? Math.min(100, Math.max(0, (used / target) * 100)) : 0;
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <p className="font-medium text-weave-800">{title}</p>
        <p className="text-sm text-weave-500">
          <span className="font-mono">{fmtUsd(used)}</span> of{" "}
          <span className="font-mono">{fmtUsd(target)}</span> used
        </p>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-weave-100 overflow-hidden">
        <div
          className="h-full bg-treasure-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-weave-500 leading-relaxed">{desc}</p>
    </div>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
      {children}
    </div>
  );
}
