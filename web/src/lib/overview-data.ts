import { createClient } from "@/lib/supabase/server";
import { fetchAlpacaSnapshot, type AlpacaPosition } from "@/lib/alpaca-snapshot";
import type { OverviewData, OVLayer, OVActivity } from "@/components/dashboard/overview-view-redesign";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/** Today's agent decision trail (approvals, vetoes, pocket skips ...) --
 *  the piece that ties what the agents DO to what the Overview SHOWS. */
async function fetchAgentActivity(): Promise<OVActivity | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/activity/today?limit=10`, {
      cache: "no-store",
      signal: AbortSignal.timeout(6000),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as OVActivity & { available?: boolean };
    if (!j || j.available === false) return null;
    return { total: j.total ?? 0, counts: j.counts ?? {}, last: j.last ?? [] };
  } catch {
    return null;
  }
}

type PaperPos = {
  ticker: string;
  asset_type: string | null;
  quantity: number | null;
  entry_price: number | null;
  strategy: string | null;
};
type ClosedRow = { realized_pnl_usd: number | null; exit_at: string | null };

const LAYER_NAME: Record<number, string> = {
  1: "Crypto",
  2: "Stock",
  3: "Options",
  4: "Extended",
  5: "Wheel",
  6: "Dividends",
  7: "KINDRIP",
};
const LAYER_RISK: Record<number, string> = {
  1: "High",
  2: "Medium",
  3: "High",
  4: "Medium",
  5: "Low",
  6: "Very Low",
  7: "Low",
};

function layerOf(assetType: string, strategy: string): number {
  const a = (assetType || "").toLowerCase();
  const s = (strategy || "").toLowerCase();
  if (a === "crypto") return 1;
  if (a === "option" || a === "options") return 3;
  if (s.startsWith("wheel") || s.includes("dividend")) return 5;
  if (s.startsWith("extended")) return 4;
  return 2;
}

export async function buildOverviewData(userId: string): Promise<OverviewData> {
  const supabase = createClient();
  const sinceIso = new Date(Date.now() - 7 * 864e5).toISOString();
  const [accountRes, openRes, closedRes, alpaca, activity] = await Promise.all([
    supabase.from("paper_accounts").select("*").eq("user_id", userId).maybeSingle(),
    supabase
      .from("paper_positions")
      .select("ticker, asset_type, quantity, entry_price, strategy")
      .eq("user_id", userId)
      .eq("status", "open"),
    supabase
      .from("paper_positions")
      .select("realized_pnl_usd, exit_at")
      .eq("user_id", userId)
      .neq("status", "open")
      .gte("exit_at", sinceIso),
    fetchAlpacaSnapshot(),
    fetchAgentActivity(),
  ]);

  const account = accountRes.data as Record<string, number> | null;
  const open = (openRes.data ?? []) as PaperPos[];
  const closed = (closedRes.data ?? []) as ClosedRow[];

  const alpacaActive = !!(alpaca?.configured && alpaca?.account);
  const agentsOnline = alpaca !== null && !alpaca.stale;
  const stale = !!alpaca?.stale;
  const asOf = alpaca?.cached_at ?? null;
  const buyingPower = alpacaActive ? Number(alpaca!.account!.buying_power) : null;
  const portfolioValue = alpacaActive
    ? Number(alpaca!.account!.equity)
    : Number(account?.current_cash_usd ?? 0) + Number(account?.vault_balance_usd ?? 0);
  const todayPnl = Number(account?.today_realized_pnl_usd ?? 0);

  const apos = (alpaca?.positions ?? []) as AlpacaPosition[];
  const findAp = (sym: string): AlpacaPosition | undefined => {
    const up = sym.toUpperCase();
    return apos.find((x) => String(x.symbol).toUpperCase() === up || String(x.symbol).toUpperCase().startsWith(up));
  };

  const layerPnl: Record<number, number> = {};
  const layerCount: Record<number, number> = {};
  let deployed = 0;
  for (const p of open) {
    const layer = layerOf(p.asset_type ?? "", p.strategy ?? "");
    const ap = findAp(String(p.ticker));
    const pnl = ap ? Number(ap.unrealized_pl) : 0;
    layerPnl[layer] = (layerPnl[layer] ?? 0) + pnl;
    layerCount[layer] = (layerCount[layer] ?? 0) + 1;
    deployed += Number(p.entry_price ?? 0) * Number(p.quantity ?? 0);
  }

  const layers: OVLayer[] = [1, 2, 3, 4, 5, 6, 7].map((id) => {
    const count = layerCount[id] ?? 0;
    return {
      id,
      name: LAYER_NAME[id],
      status: count > 0 ? "active" : "idle",
      pnl: Math.round((layerPnl[id] ?? 0) * 100) / 100,
      agents: count > 0 ? 1 : 0,
      risk: LAYER_RISK[id],
      idleReason: count > 0 ? undefined : "No open position right now",
    };
  });
  const layersActive = layers.filter((l) => l.status === "active").length;
  const deployedPct = portfolioValue > 0 ? (deployed / portfolioValue) * 100 : null;

  const byDay = new Map<string, number>();
  for (const r of closed) {
    if (!r.exit_at) continue;
    const day = String(r.exit_at).slice(0, 10);
    byDay.set(day, (byDay.get(day) ?? 0) + Number(r.realized_pnl_usd ?? 0));
  }
  const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const week: { d: string; v: number }[] = [];
  for (let i = 6; i >= 0; i--) {
    const dt = new Date(Date.now() - i * 864e5);
    const key = dt.toISOString().slice(0, 10);
    week.push({ d: WD[dt.getUTCDay()], v: Math.round((byDay.get(key) ?? 0) * 100) / 100 });
  }
  const weekPnl = week.reduce((s, x) => s + x.v, 0);

  return { portfolioValue, weekPnl, todayPnl, deployed, deployedPct, layersActive, week, layers, live: true, agentsOnline, buyingPower, stale, asOf, activity };
}
