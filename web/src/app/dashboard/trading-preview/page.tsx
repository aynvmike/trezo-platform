import { createClient } from "@/lib/supabase/server";
import {
  TradingViewRedesign,
  type TradingData,
  type TVPosition,
  type TVFeed,
} from "@/components/dashboard/trading-view-redesign";
import { FadeIn } from "@/components/dashboard/fade-in";
import { fetchAlpacaSnapshot, type AlpacaPosition } from "@/lib/alpaca-snapshot";
import { describeAgentMessage, agentLabel, type FeedMessage } from "@/lib/agent-message";

export const dynamic = "force-dynamic";

type PaperPos = {
  id: string;
  ticker: string;
  asset_type: string | null;
  side: string | null;
  quantity: number | null;
  entry_price: number | null;
  strategy: string | null;
};

type MsgRow = {
  id: string | number;
  agent_name: string;
  kind: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

function layerFor(assetType: string, strategy: string): { layer: number; name: string } {
  const a = (assetType || "").toLowerCase();
  const s = (strategy || "").toLowerCase();
  if (a === "crypto") return { layer: 1, name: "Crypto" };
  if (a === "option" || a === "options") return { layer: 3, name: "Options" };
  if (s.startsWith("wheel") || s.includes("dividend")) return { layer: 5, name: "Wheel" };
  if (s.startsWith("extended")) return { layer: 4, name: "Extended" };
  return { layer: 2, name: "Stock" };
}

function agentLayer(agent: string): number {
  const m: Record<string, number> = {
    crypto_scanner: 1,
    stms_scanner: 2,
    orb_scanner: 2,
    pattern_detection: 2,
    options_scanner: 3,
    extended_scanner: 4,
    dividend_manager: 5,
    kindrip: 7,
  };
  return m[agent] ?? 0;
}

function feedType(kind: string): string {
  if (kind === "close") return "exit";
  if (kind === "veto" || kind === "alert" || kind === "error") return "alert";
  return "open";
}

export default async function TradingPreviewPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="mx-auto max-w-6xl p-6 text-sm text-[rgb(var(--muted-foreground))]">
        Please sign in to view the Trading dashboard.
      </div>
    );
  }

  const [accountRes, openRes, msgsRes, alpaca, botRes, profileRes] = await Promise.all([
    supabase.from("paper_accounts").select("*").eq("user_id", user.id).maybeSingle(),
    supabase
      .from("paper_positions")
      .select("id, ticker, asset_type, side, quantity, entry_price, strategy")
      .eq("user_id", user.id)
      .eq("status", "open")
      .order("entry_at", { ascending: false }),
    supabase
      .from("agent_messages")
      .select("id, agent_name, kind, payload, created_at")
      .or(`user_id.eq.${user.id},user_id.is.null`)
      .order("created_at", { ascending: false })
      .limit(14),
    fetchAlpacaSnapshot(),
    supabase.from("bot_settings").select("auto_trade_enabled").eq("user_id", user.id).maybeSingle(),
    supabase.from("profiles").select("daily_loss_limit_usd").eq("user_id", user.id).maybeSingle(),
  ]);

  const account = accountRes.data as Record<string, number> | null;
  const open = (openRes.data ?? []) as PaperPos[];
  const alpacaActive = !!(alpaca?.configured && alpaca?.account);
  const aAcct = alpaca?.account;
  const portfolioValue = alpacaActive
    ? Number(aAcct!.equity)
    : Number(account?.current_cash_usd ?? 0) + Number(account?.vault_balance_usd ?? 0);
  const todayPnl = Number(account?.today_realized_pnl_usd ?? 0);

  const apos = (alpaca?.positions ?? []) as AlpacaPosition[];
  const findAp = (sym: string): AlpacaPosition | undefined => {
    const up = sym.toUpperCase();
    return apos.find(
      (x) => String(x.symbol).toUpperCase() === up || String(x.symbol).toUpperCase().startsWith(up)
    );
  };

  const positions: TVPosition[] = open.map((p) => {
    const { layer, name } = layerFor(p.asset_type ?? "", p.strategy ?? "");
    const ap = findAp(String(p.ticker));
    return {
      id: p.id,
      ticker: p.ticker,
      side: String(p.side ?? "").toUpperCase(),
      layer: name,
      chip: layer,
      entry: Number(p.entry_price ?? 0),
      qty: Number(p.quantity ?? 0),
      current: ap ? Number(ap.current_price) : null,
      pnl: ap ? Number(ap.unrealized_pl) : null,
      pct: ap ? Number(ap.unrealized_plpc) * 100 : null,
    };
  });

  const deployed = positions.reduce((a, p) => a + p.entry * p.qty, 0);
  const deployedPct = portfolioValue > 0 ? (deployed / portfolioValue) * 100 : null;

  const feed: TVFeed[] = ((msgsRes.data ?? []) as MsgRow[]).map((m) => {
    const fm: FeedMessage = {
      id: String(m.id),
      agent_name: m.agent_name,
      kind: m.kind,
      payload: m.payload ?? {},
      created_at: m.created_at,
    };
    return {
      id: String(m.id),
      time: String(m.created_at).slice(11, 16),
      agent: agentLabel(m.agent_name),
      action: describeAgentMessage(fm),
      reason: "",
      layer: agentLayer(m.agent_name),
      type: feedType(m.kind),
    };
  });

  const botRow = botRes.data as { auto_trade_enabled?: boolean } | null;
  const profileRow = profileRes.data as { daily_loss_limit_usd?: number } | null;

  const data: TradingData = {
    portfolioValue,
    todayPnl,
    todayPct: null,
    deployed,
    deployedPct,
    openCount: positions.length,
    pnlSeries: [0, todayPnl],
    positions,
    feed,
    market: [],
    paperMode: true,
    autoTrade: botRow?.auto_trade_enabled !== false,
    riskLimit: Number(profileRow?.daily_loss_limit_usd ?? 100),
    asOf: alpaca?.as_of ? "as of " + String(alpaca.as_of).slice(11, 16) + " UTC" : "live account",
    live: true,
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <FadeIn>
        <TradingViewRedesign data={data} />
      </FadeIn>
    </div>
  );
}
