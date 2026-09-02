import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { FadeIn } from "@/components/dashboard/fade-in";
import {
  TradingViewRedesign,
  type TradingData,
  type TVPosition,
  type TVFeed,
} from "@/components/dashboard/trading-view-redesign";
import { fetchAlpacaSnapshot, type AlpacaPosition, fetchPositionAdvice } from "@/lib/alpaca-snapshot";
import { describeAgentMessage, agentLabel, type FeedMessage } from "@/lib/agent-message";
import { Disclosure } from "@/components/ui/disclosure";
import { ExitAdvisorAlerts } from "@/components/dashboard/exit-advisor-alerts";
import { CapitalPressurePanel } from "@/components/dashboard/capital-pressure-panel";
import { MarketSidePanelServer } from "@/components/dashboard/market-side-panel-server";
import { CyclesPanel } from "@/components/dashboard/cycles-panel";
import { StrategyWindows } from "@/components/dashboard/strategy-windows";
import { Iso20022CryptoPanel } from "@/components/dashboard/iso20022-crypto-panel";
import { RunScannerButton } from "@/components/dashboard/run-scanner-button";
import { DiagnoseNowButton } from "@/components/dashboard/diagnose-now-button";
import { StocksReconcileButton } from "@/components/dashboard/stocks-reconcile-button";
import { ManualTradeButton } from "@/components/dashboard/manual-trade-button";
import { ScannerPulse } from "@/components/dashboard/scanner-pulse";
import { VetoReasonsPanel } from "@/components/dashboard/veto-reasons-panel";
import { SignalTracePanel } from "@/components/dashboard/signal-trace-panel";
import { TodaysExecutionFeed } from "@/components/dashboard/todays-execution-feed";
import { BotSettingsPanel } from "@/components/dashboard/bot-settings-panel";
import { LoadError, LoadErrors, loadResult, failuresOf } from "@/components/dashboard/load-error";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";
import { requestClose } from "./_actions";

export const dynamic = "force-dynamic";

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}
function agoLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 60_000) return "just now";
  if (ms < 3_600_000) return Math.floor(ms / 60_000) + "m ago";
  if (ms < 86_400_000) return Math.floor(ms / 3_600_000) + "h ago";
  return Math.floor(ms / 86_400_000) + "d ago";
}
async function fetchForexQuotes(symbols: string[]): Promise<Record<string, number>> {
  // Live spot for forex pairs from Kraken's public ticker (the same venue
  // the agents' forex data comes from). Fail-quiet: a miss just leaves the
  // card without a live price, exactly as before.
  const out: Record<string, number> = {};
  await Promise.all(symbols.map(async (sym) => {
    try {
      const res = await fetch(
        `https://api.kraken.com/0/public/Ticker?pair=${encodeURIComponent(sym)}`,
        { next: { revalidate: 10 } },
      );
      if (!res.ok) return;
      const j = (await res.json()) as { result?: Record<string, { c?: string[] }> };
      const first = j.result ? Object.values(j.result)[0] : undefined;
      const px = first?.c?.[0] != null ? Number(first.c[0]) : NaN;
      if (Number.isFinite(px) && px > 0) out[sym] = px;
    } catch { /* price stays unavailable */ }
  }));
  return out;
}

function layerFor(assetType: string, strategy: string): { layer: number; name: string } {
  const a = (assetType || "").toLowerCase();
  const s = (strategy || "").toLowerCase();
  if (a === "crypto") return { layer: 1, name: "Crypto" };
  if (a === "forex") return { layer: 6, name: "Forex" };
  if (a === "option" || a === "options") return { layer: 3, name: "Options" };
  if (s.startsWith("wheel") || s.includes("dividend")) return { layer: 5, name: "Wheel" };
  if (s.startsWith("extended")) return { layer: 4, name: "Extended" };
  return { layer: 2, name: "Stock" };
}
function agentLayerOf(agent: string): number {
  const m: Record<string, number> = {
    crypto_scanner: 1, stms_scanner: 2, orb_scanner: 2, pattern_detection: 2,
    options_scanner: 3, extended_scanner: 4, dividend_manager: 5, kindrip: 7,
  };
  return m[agent] ?? 0;
}
function feedType(kind: string): string {
  if (kind === "close") return "exit";
  if (kind === "veto" || kind === "alert" || kind === "error") return "alert";
  return "open";
}

const STRATEGY_THESIS: Record<string, string> = {
  wheel_csp: "Cash-secured put — collecting premium; held until it decays to profit or you're assigned shares at a discount.",
  cash_secured_put: "Cash-secured put — collecting premium; held until it decays to profit or you're assigned shares at a discount.",
  wheel_cc: "Covered call — collecting premium against shares you already hold.",
  wheel: "Wheel income — collecting option premium on a quality name.",
  stms: "Short-term momentum swing — riding the move until the target hits or momentum fades.",
  orb: "Opening-range breakout — an intraday momentum push toward its target.",
  pattern: "Technical pattern setup — held toward target while the pattern stays valid.",
  extended: "Multi-day swing — held across sessions toward a larger target.",
  hodl: "Patient accumulation — held with a catastrophe stop, trailing up once it runs.",
  forex_swing: "Forex swing — a currency-pair move held toward its target with a hard stop; prices move in fractions of a cent, so the position is sized in units.",
  swing: "Crypto swing — held toward target with step-ladder profit locks.",
  dca: "Dollar-cost accumulation — building the position in steps toward target.",
  dividend: "Income position — held to capture the distribution.",
  yieldmax: "Aggressive income — held to capture high distributions.",
};
function thesisFor(strategy: string, assetType: string): string {
  const s = (strategy || "").toLowerCase();
  for (const key of Object.keys(STRATEGY_THESIS)) {
    if (s.startsWith(key) || s.includes(key)) return STRATEGY_THESIS[key];
  }
  if ((assetType || "").toLowerCase() === "crypto") return "Crypto position — held on its entry thesis with a protective stop.";
  return "Held on its entry thesis, working toward its target.";
}
function pxFmt(n: number): string {
  if (n >= 1000) return "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (n < 2) return "$" + n.toFixed(4); // forex pairs + sub-$2 names move in fractions of a cent
  return "$" + n.toFixed(2);
}
function planText(side: string, entry: number, current: number | null, target: number | null, stop: number | null): string {
  const isLong = side !== "SHORT";
  if (current == null) {
    if (target != null && stop != null) return `Sells at target ${pxFmt(target)} for profit; stop ${pxFmt(stop)} caps the loss. Live price unavailable right now.`;
    if (target != null) return `Target ${pxFmt(target)} — sells there for profit. Live price unavailable right now.`;
    return "Held on thesis — live price unavailable right now.";
  }
  const parts: string[] = [];
  const inProfit = isLong ? current >= entry : current <= entry;
  if (inProfit) {
    parts.push("In profit");
    if (target != null) {
      const toT = isLong ? ((target - current) / current) * 100 : ((current - target) / current) * 100;
      parts.push(`target ${pxFmt(target)} (${toT >= 0 ? "+" : ""}${toT.toFixed(1)}% away)`);
    }
    parts.push("the profit-lock trails the stop up so a pullback still books the gain");
  } else {
    const beNeed = isLong ? ((entry - current) / current) * 100 : ((current - entry) / current) * 100;
    parts.push(`break-even at ${pxFmt(entry)} (needs ${beNeed >= 0 ? "+" : ""}${beNeed.toFixed(1)}%)`);
    if (target != null) {
      const toT = isLong ? ((target - current) / current) * 100 : ((current - target) / current) * 100;
      parts.push(`target ${pxFmt(target)} = ${toT >= 0 ? "+" : ""}${toT.toFixed(1)}% from here`);
    }
    if (stop != null) {
      const toS = isLong ? ((current - stop) / current) * 100 : ((stop - current) / current) * 100;
      parts.push(`cuts the loss at stop ${pxFmt(stop)} (${toS >= 0 ? "−" : "+"}${Math.abs(toS).toFixed(1)}%)`);
    }
    if (target == null && stop == null) parts.push("no target or stop set yet — held on thesis while the agent manages the exit");
  }
  return parts.join(" · ");
}

type OpenPos = {
  id: string; ticker: string; asset_type: string | null; side: string | null;
  quantity: number | null; entry_price: number | null; strategy: string | null;
  stop_price: number | null; target_price: number | null; entry_at: string | null;
};
type ClosedPos = {
  id: string; ticker: string; side: string; entry_price: number;
  exit_price: number | null; realized_pnl_usd: number | null; status: string;
};
type MsgRow = {
  id: string | number; agent_name: string; kind: string;
  payload: Record<string, unknown> | null; created_at: string;
};

export default async function PaperPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/paper");

  // rv:web-pages (Overview MAJOR, swept here): book tables are keyed by
  // BOOK since 0047; resolve the person's books and read across them.
  const booksLoad = await getOwnerBookKeys(supabase, user.id);
  const keys = bookQueryKeys(booksLoad.data);

  const [accountRes, openRes, closedRes, msgsRes, alpaca, advice, botRes, profileRes] = await Promise.all([
    supabase
      .from("paper_accounts")
      .select("current_cash_usd, vault_balance_usd, today_realized_pnl_usd")
      .in("user_id", keys),
    supabase
      .from("paper_positions")
      .select("id, ticker, asset_type, side, quantity, entry_price, strategy, stop_price, target_price, entry_at")
      .in("user_id", keys).eq("status", "open").order("entry_at", { ascending: false }),
    supabase
      .from("paper_positions")
      .select("id, ticker, side, entry_price, exit_price, realized_pnl_usd, status")
      .in("user_id", keys).neq("status", "open").order("exit_at", { ascending: false }).limit(20),
    supabase
      .from("agent_messages")
      .select("id, agent_name, kind, payload, created_at")
      .or(`user_id.eq.${user.id},user_id.is.null`)
      .order("created_at", { ascending: false }).limit(14),
    fetchAlpacaSnapshot(),
    fetchPositionAdvice(),
    supabase.from("bot_settings").select("auto_trade_enabled").eq("user_id", user.id).maybeSingle(),
    supabase.from("profiles").select("daily_loss_limit_usd").eq("user_id", user.id).maybeSingle(),
  ]);

  // PAGES-03: keep "read failed" distinct from "nothing there". The
  // account + open-position reads feed every headline number, so if
  // either failed the trading view is replaced by the error card rather
  // than rendering a $0 / flat book.
  type AcctRow = {
    current_cash_usd: number | null;
    vault_balance_usd: number | null;
    today_realized_pnl_usd: number | null;
  };
  const accountLoad = loadResult<AcctRow[]>("paper_accounts", accountRes, []);
  const openLoad = loadResult<OpenPos[]>("paper_positions", openRes, []);
  const closedLoad = loadResult<ClosedPos[]>("paper_positions (closed)", closedRes, []);
  const msgsLoad = loadResult<MsgRow[]>("agent_messages", msgsRes, []);
  const botLoad = loadResult<{ auto_trade_enabled?: boolean } | null>("bot_settings", botRes);
  const profileLoad = loadResult<{ daily_loss_limit_usd?: number } | null>("profiles", profileRes);
  // A failed book resolution is a core failure: without the keys, every
  // book read above is an empty read, not an empty book.
  const coreFailures = failuresOf(booksLoad, accountLoad, openLoad);
  const sideFailures = failuresOf(closedLoad, msgsLoad, botLoad, profileLoad);
  // One paper_accounts row per book -- the person's numbers are the sum.
  const accounts = accountLoad.data ?? [];
  const sumAcct = (k: keyof AcctRow) => accounts.reduce((s, a) => s + Number(a[k] ?? 0), 0);
  const open = openLoad.data ?? [];
  const closed = closedLoad.data ?? [];
  const fxSymbols = open
    .filter((p) => (p.asset_type ?? "").toLowerCase() === "forex")
    .map((p) => String(p.ticker).toUpperCase());
  const fxQuotes: Record<string, number> = fxSymbols.length
    ? await fetchForexQuotes(fxSymbols)
    : {};
  const alpacaActive = !!(alpaca?.configured && alpaca?.account);
  const agentsOnline = alpaca !== null && !alpaca.stale;
  const snapshotStale = !!alpaca?.stale;
  const snapshotAsOf = alpaca?.cached_at ?? null;
  const aAcct = alpaca?.account;
  const displayCash = alpacaActive ? Number(aAcct!.cash) : sumAcct("current_cash_usd");
  const portfolioValue = alpacaActive
    ? Number(aAcct!.equity)
    : sumAcct("current_cash_usd") + sumAcct("vault_balance_usd");
  const todayPnl = sumAcct("today_realized_pnl_usd");

  const apos = (alpaca?.positions ?? []) as AlpacaPosition[];
  const findAp = (sym: string): AlpacaPosition | undefined => {
    const up = sym.toUpperCase();
    return apos.find(
      (x) => String(x.symbol).toUpperCase() === up || String(x.symbol).toUpperCase().startsWith(up)
    );
  };

  const matchedSymbols = new Set<string>();
  const positions: TVPosition[] = open.map((p) => {
    const { layer, name } = layerFor(p.asset_type ?? "", p.strategy ?? "");
    const ap = findAp(String(p.ticker));
    if (ap) matchedSymbols.add(String(ap.symbol).toUpperCase());
    const sideU = String(p.side ?? "").toUpperCase();
    const entryN = Number(p.entry_price ?? 0);
    const isLong = sideU !== "SHORT";
    const isFx = (p.asset_type ?? "").toLowerCase() === "forex";
    const fxPx = isFx ? (fxQuotes[String(p.ticker).toUpperCase()] ?? null) : null;
    const fxQty = Number(p.quantity ?? 0);
    const fxPnl = isFx && fxPx != null && entryN > 0
      ? (isLong ? fxPx - entryN : entryN - fxPx) * fxQty
      : null;
    const curN = ap ? Number(ap.current_price) : fxPx;
    const stopN = p.stop_price != null ? Number(p.stop_price) : null;
    const targetN = p.target_price != null ? Number(p.target_price) : null;
    const locked = stopN != null && entryN > 0 && (isLong ? stopN > entryN : stopN < entryN);
    return {
      id: p.id, ticker: p.ticker, side: sideU,
      layer: name, chip: layer, entry: entryN, qty: Number(p.quantity ?? 0),
      current: curN,
      pnl: ap ? Number(ap.unrealized_pl) : fxPnl,
      pct: ap
        ? Number(ap.unrealized_plpc) * 100
        : (fxPnl != null && entryN > 0 && fxQty > 0
            ? (fxPnl / (entryN * fxQty)) * 100
            : null),
      flag: ap
        ? ("live" as const)
        : ((p.asset_type ?? "").toLowerCase() === "crypto" || isFx
            ? ("modeled" as const)
            : ("unconfirmed" as const)),
      // Mike 2026-07-28: asset kind at a glance + is it REALLY at the
      // broker (13 of 18 positions were modeled-only and invisible on
      // his Alpaca screen), plus the agents' recommendation.
      assetKind: (((p.asset_type ?? "").toLowerCase() === "crypto")
        ? "Crypto" : isFx ? "Forex"
        : ((p.asset_type ?? "").toLowerCase().startsWith("option")
            ? "Option" : "Stock")) as "Crypto" | "Stock" | "Forex" | "Option",
      atBroker: advice[String(p.ticker).toUpperCase()]?.at_broker ?? (ap ? true : null),
      verdict: advice[String(p.ticker).toUpperCase()]?.verdict,
      verdictWhy: advice[String(p.ticker).toUpperCase()]?.why,
      verdictAction: advice[String(p.ticker).toUpperCase()]?.action,
      stop: stopN, target: targetN,
      heldSince: p.entry_at ? agoLabel(p.entry_at) : undefined,
      why: thesisFor(p.strategy ?? "", p.asset_type ?? ""),
      plan: planText(sideU, entryN, curN, targetN, stopN),
      locked,
    };
  });

  // Show everything actually held at the broker, even if Trezo's ledger has
  // not caught it yet -- append any Alpaca position not already listed.
  const brokerOnly: TVPosition[] = apos
    .filter((ap) => !matchedSymbols.has(String(ap.symbol).toUpperCase()))
    .map((ap) => {
      const e = Number(ap.avg_entry_price ?? 0);
      const c = Number(ap.current_price ?? 0);
      const isLong = String(ap.side ?? "long").toLowerCase() !== "short";
      const inProfit = isLong ? c >= e : c <= e;
      return {
        id: "alpaca:" + String(ap.symbol), ticker: String(ap.symbol),
        side: String(ap.side ?? "long").toUpperCase(), layer: "Broker", chip: 0,
        entry: e, qty: Number(ap.qty ?? 0), current: c,
        pnl: Number(ap.unrealized_pl ?? 0), pct: Number(ap.unrealized_plpc ?? 0) * 100,
        flag: "live" as const, stop: null, target: null, heldSince: undefined,
        why: "Held at your Alpaca broker, not yet tracked in Trezo's ledger \u2014 the agents reconcile it shortly. Shown so nothing is hidden.",
        plan: inProfit
          ? "In profit at the broker \u2014 the agents will adopt and manage it on the next reconcile."
          : "The agents will adopt and manage it on the next reconcile (a stop and target get set then).",
        locked: false,
      };
    });
  const positionsAll: TVPosition[] = [...positions, ...brokerOnly];

  const deployed = positionsAll.reduce((acc, p) => acc + p.entry * p.qty, 0);
  const deployedPct = portfolioValue > 0 ? (deployed / portfolioValue) * 100 : null;

  const feed: TVFeed[] = (msgsLoad.data ?? []).map((m) => {
    const fm: FeedMessage = {
      id: String(m.id), agent_name: m.agent_name, kind: m.kind,
      payload: m.payload ?? {}, created_at: m.created_at,
    };
    return {
      id: String(m.id), time: String(m.created_at).slice(11, 16), agent: agentLabel(m.agent_name),
      action: describeAgentMessage(fm), reason: "", layer: agentLayerOf(m.agent_name), type: feedType(m.kind),
    };
  });

  const botRow = botLoad.data ?? null;
  const profileRow = profileLoad.data ?? null;

  const data: TradingData = {
    portfolioValue, todayPnl, todayPct: null, deployed, deployedPct,
    openCount: positionsAll.length, pnlSeries: [0, todayPnl], positions: positionsAll, feed, market: [],
    paperMode: true, autoTrade: botRow?.auto_trade_enabled !== false,
    riskLimit: Number(profileRow?.daily_loss_limit_usd ?? 100),
    asOf: snapshotStale ? "last known" : agentsOnline ? "live account" : "agents offline",
    live: true,
  };

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 space-y-6">
      <ExitAdvisorAlerts />

      <div className="rounded-xl border border-weave-100 bg-white px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
        <span className="flex items-center gap-1.5">
          <span className={cn("h-2 w-2 rounded-full", agentsOnline ? "bg-emerald-500" : "bg-red-500")} />
          <span className="text-weave-500">Agents</span>
          <span className={cn("font-medium", agentsOnline ? "text-emerald-700" : "text-red-700")}>{agentsOnline ? "Live" : "Offline"}</span>
        </span>
        <span className="text-weave-500">
          Buying power:{" "}
          <span className="font-mono text-weave-800">{alpacaActive ? fmtUsd(displayCash) : "—"}</span>
        </span>
        {agentsOnline ? (
          displayCash === 0 ? (
            <span className="text-xs text-weave-500">Agents live, but $0 buying power to trade.</span>
          ) : null
        ) : snapshotStale ? (
          <span className="text-xs text-amber-700">Showing last known data{snapshotAsOf ? " · as of " + agoLabel(snapshotAsOf) : ""} — agents offline. Start it on port 8001 for live.</span>
        ) : (
          <span className="text-xs text-amber-700">Agents service offline — live numbers unavailable. Start it on port 8001.</span>
        )}
      </div>

      <LoadErrors failures={sideFailures} />
      {coreFailures.length > 0 ? (
        <LoadErrors failures={coreFailures} />
      ) : (
        <FadeIn>
          <TradingViewRedesign data={data} closeAction={requestClose} />
        </FadeIn>
      )}

      <CapitalPressurePanel userId={user.id} />

      <Disclosure title={closedLoad.failure ? "Recent trades" : `Recent trades (${closed.length})`}>
        {closedLoad.failure ? (
          <LoadError {...closedLoad.failure} />
        ) : closed.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-center text-sm text-weave-500">No closed trades yet.</div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th><th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3 text-right">Entry</th><th className="px-4 py-3 text-right">Exit</th>
                  <th className="px-4 py-3 text-right">P&amp;L</th><th className="px-4 py-3">Closed by</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((p) => {
                  const pnl = Number(p.realized_pnl_usd ?? 0);
                  return (
                    <tr key={p.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">{p.ticker}</td>
                      <td className="px-4 py-3 text-weave-600">{p.side}</td>
                      <td className="px-4 py-3 text-right font-mono">{fmtUsd(p.entry_price)}</td>
                      <td className="px-4 py-3 text-right font-mono">{fmtUsd(p.exit_price)}</td>
                      <td className={cn("px-4 py-3 text-right font-mono", pnl > 0 && "text-emerald-700", pnl < 0 && "text-red-600")}>{fmtUsd(pnl)}</td>
                      <td className="px-4 py-3 text-xs text-weave-500">{String(p.status).replace("closed_", "")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Disclosure>

      <Disclosure title="Tools &amp; diagnostics">
        <div className="space-y-4">
          <section className="grid gap-3 sm:grid-cols-3">
            <RunScannerButton name="pattern_detection" label="Run stock scan now" hint="Runs the Pattern Detection scanner immediately (watchlist + market-wide)." />
            <DiagnoseNowButton />
            <StocksReconcileButton />
          </section>
          <ManualTradeButton />
          <MarketSidePanelServer />
          <CyclesPanel userId={user.id} />
          <StrategyWindows />
          <Iso20022CryptoPanel />
          <section className="grid gap-3 md:grid-cols-2">
            <ScannerPulse userId={user.id} />
            <VetoReasonsPanel userId={user.id} />
          </section>
          <Disclosure title="Signal trace — last hour">
            <SignalTracePanel userId={user.id} />
          </Disclosure>
          <Disclosure title="Today's execution feed">
            <TodaysExecutionFeed userId={user.id} />
          </Disclosure>
          <Disclosure title="Bot settings — in force">
            <BotSettingsPanel userId={user.id} />
          </Disclosure>
        </div>
      </Disclosure>

      <p className="text-[11px] text-weave-500 italic">
        Want a comprehensive view of today&apos;s activity?{" "}
        <Link href="/dashboard/agents" className="underline hover:text-weave-800">Open the Agents page →</Link>
      </p>
    </div>
  );
}
