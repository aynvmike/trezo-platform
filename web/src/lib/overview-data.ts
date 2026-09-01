import { createClient } from "@/lib/supabase/server";
import { fetchAlpacaSnapshot, type AlpacaPosition } from "@/lib/alpaca-snapshot";
import type { OverviewData, OVLayer, OVActivity } from "@/components/dashboard/overview-view-redesign";
import type { HeroGoal } from "@/components/dashboard/woven-basket-hero";
import { loadResult, failuresOf, type LoadFailure } from "@/components/dashboard/load-error";

/**
 * PAGES-03: `data` is null whenever any Supabase read failed, and
 * `failures` says which table(s). The Overview must not render a
 * $0 / all-idle basket on a broken query.
 */
export type OverviewLoad =
  | { data: OverviewData; failures: [] }
  | { data: null; failures: LoadFailure[] };

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

/** The agents' daily income goal (Mike 2026-07-13) -- paycheck ladder rung
 *  for the account size + today's realized progress toward it. */
async function fetchDailyGoal(): Promise<HeroGoal | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/goal/today`, {
      cache: "no-store",
      signal: AbortSignal.timeout(6000),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as HeroGoal & { available?: boolean };
    if (!j || j.available === false) return null;
    return {
      goal: j.goal ?? 50,
      label: j.label ?? "grind",
      realized: j.realized ?? 0,
      hit: !!j.hit,
      pct: j.pct ?? 0,
      week_goal: j.week_goal ?? null,
      week_realized: j.week_realized ?? null,
    };
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
type OptRow = {
  underlying: string;
  strategy: string | null;
  option_type: string | null;
  strike: number | null;
  contracts: number | null;
  expiration: string | null;
};

/** OCC symbol for an options row — matches Alpaca's position symbols. */
function occSymbol(o: OptRow): string {
  const exp = String(o.expiration ?? "").slice(0, 10); // YYYY-MM-DD
  if (exp.length < 10 || !o.strike) return "";
  const cp = String(o.option_type ?? "put").toLowerCase().startsWith("c") ? "C" : "P";
  const k = String(Math.round(Number(o.strike) * 1000)).padStart(8, "0");
  return `${String(o.underlying).toUpperCase()}${exp.slice(2, 4)}${exp.slice(5, 7)}${exp.slice(8, 10)}${cp}${k}`;
}

const LAYER_NAME: Record<number, string> = {
  1: "Crypto",
  2: "Stock",
  3: "Options",
  4: "Extended",
  5: "Wheel",
  6: "Dividends",
  7: "KINDRIP",
  8: "Forex",
};
const LAYER_RISK: Record<number, string> = {
  1: "High",
  2: "Medium",
  3: "High",
  4: "Medium",
  5: "Low",
  6: "Very Low",
  7: "Low",
  8: "Medium",
};

function layerOf(assetType: string, strategy: string): number {
  const a = (assetType || "").toLowerCase();
  const s = (strategy || "").toLowerCase();
  if (a === "forex" || s.startsWith("forex")) return 8;
  if (a === "crypto") return 1;
  if (a === "option" || a === "options") return 3;
  if (s.startsWith("wheel") || s.includes("dividend")) return 5;
  if (s.startsWith("extended")) return 4;
  return 2;
}

export async function buildOverviewData(userId: string): Promise<OverviewLoad> {
  const supabase = createClient();
  const sinceIso = new Date(Date.now() - 7 * 864e5).toISOString();
  const [accountRes, openRes, closedRes, alpaca, activity, goalInfo, optRes] = await Promise.all([
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
    fetchDailyGoal(),
    supabase
      .from("options_positions")
      .select("underlying, strategy, option_type, strike, contracts, expiration")
      .eq("user_id", userId)
      .eq("status", "open"),
  ]);

  const accountLoad = loadResult<Record<string, number> | null>("paper_accounts", accountRes);
  const openLoad = loadResult<PaperPos[]>("paper_positions", openRes, []);
  const closedLoad = loadResult<ClosedRow[]>("paper_positions (closed)", closedRes, []);
  const optLoad = loadResult<OptRow[]>("options_positions", optRes, []);
  const failures = failuresOf(accountLoad, openLoad, closedLoad, optLoad);
  if (failures.length > 0) return { data: null, failures };

  const account = accountLoad.data ?? null;
  const open = openLoad.data ?? [];
  const closed = closedLoad.data ?? [];

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

  // Options positions live in their OWN table (2026-07-06: three live
  // CSPs were invisible on the Overview). Fold them into layers 3/5 with
  // Alpaca's mark-to-market P/L, matched by OCC symbol.
  const optRows = optLoad.data ?? [];
  for (const o of optRows) {
    const layer = String(o.strategy ?? "").startsWith("wheel") ? 5 : 3;
    const occ = occSymbol(o);
    const ap = occ ? apos.find((x) => String(x.symbol).toUpperCase() === occ) : undefined;
    const pnl = ap ? Number(ap.unrealized_pl) : 0;
    layerPnl[layer] = (layerPnl[layer] ?? 0) + pnl;
    layerCount[layer] = (layerCount[layer] ?? 0) + 1;
    deployed += Number(o.strike ?? 0) * 100 * Number(o.contracts ?? 1);
  }

  const layers: OVLayer[] = [1, 2, 3, 4, 5, 6, 7, 8].map((id) => {
    const count = layerCount[id] ?? 0;
    return {
      id,
      name: LAYER_NAME[id],
      status: count > 0 ? "active" : "idle",
      pnl: Math.round((layerPnl[id] ?? 0) * 100) / 100,
      positions: count,
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

  return {
    data: { portfolioValue, weekPnl, todayPnl, deployed, deployedPct, layersActive, week, layers, live: true, agentsOnline, buyingPower, stale, asOf, activity, goal: goalInfo },
    failures: [],
  };
}
