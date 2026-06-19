import { createClient } from "@/lib/supabase/server";
import {
  AgentsViewRedesign,
  type AgentsData,
  type AGAgent,
} from "@/components/dashboard/agents-view-redesign";
import { FadeIn } from "@/components/dashboard/fade-in";
import { describeAgentMessage, type FeedMessage } from "@/lib/agent-message";

export const dynamic = "force-dynamic";

type MsgRow = {
  agent_name: string;
  kind: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};
type OpenRow = { asset_type: string | null; strategy: string | null };
type ClosedRow = {
  realized_pnl_usd: number | null;
  entry_at: string | null;
  exit_at: string | null;
  asset_type: string | null;
  strategy: string | null;
};

const DEFS: { id: number; name: string; layer: number; layerName: string; strategy: string; keys: string[] }[] = [
  { id: 1, name: "Crypto Bot", layer: 1, layerName: "Crypto", strategy: "Momentum + RSI reversal on crypto", keys: ["crypto_scanner"] },
  { id: 2, name: "Stock Bot", layer: 2, layerName: "Stock", strategy: "Breakout + pullback on the daily trend", keys: ["stms_scanner", "orb_scanner", "pattern_detection"] },
  { id: 3, name: "Options Bot", layer: 3, layerName: "Options", strategy: "Directional debit spreads, low IV rank", keys: ["options_scanner"] },
  { id: 4, name: "Extended Bot", layer: 4, layerName: "Extended", strategy: "Multi-day swings and events", keys: ["extended_scanner"] },
  { id: 5, name: "Wheel Bot", layer: 5, layerName: "Wheel", strategy: "Cash-secured puts into covered calls", keys: ["dividend_manager"] },
  { id: 6, name: "Dividends Bot", layer: 6, layerName: "Dividends", strategy: "High-yield dividend capture", keys: ["dividend_manager"] },
  { id: 7, name: "KINDRIP Bot", layer: 7, layerName: "KINDRIP", strategy: "Long-only kind and responsible ETFs", keys: ["kindrip"] },
];

function layerOf(assetType: string, strategy: string): number {
  const a = (assetType || "").toLowerCase();
  const s = (strategy || "").toLowerCase();
  if (a === "crypto") return 1;
  if (a === "option" || a === "options") return 3;
  if (s.startsWith("wheel") || s.includes("dividend")) return 5;
  if (s.startsWith("extended")) return 4;
  return 2;
}

function fmtHold(hours: number): string {
  if (!isFinite(hours) || hours <= 0) return "—";
  return hours < 24 ? hours.toFixed(1) + "h" : (hours / 24).toFixed(1) + "d";
}

export default async function AgentsPreviewPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="mx-auto max-w-6xl p-6 text-sm text-[rgb(var(--muted-foreground))]">
        Please sign in to view the Agents dashboard.
      </div>
    );
  }

  const dayIso = new Date(Date.now() - 1 * 864e5).toISOString();
  const monthIso = new Date(Date.now() - 30 * 864e5).toISOString();
  const todayKey = new Date().toISOString().slice(0, 10);

  const [msgsRes, openRes, closedRes] = await Promise.all([
    supabase
      .from("agent_messages")
      .select("agent_name, kind, payload, created_at")
      .or(`user_id.eq.${user.id},user_id.is.null`)
      .gte("created_at", dayIso)
      .order("created_at", { ascending: false })
      .limit(150),
    supabase
      .from("paper_positions")
      .select("asset_type, strategy")
      .eq("user_id", user.id)
      .eq("status", "open"),
    supabase
      .from("paper_positions")
      .select("realized_pnl_usd, entry_at, exit_at, asset_type, strategy")
      .eq("user_id", user.id)
      .neq("status", "open")
      .gte("exit_at", monthIso),
  ]);

  const msgs = (msgsRes.data ?? []) as MsgRow[];
  const open = (openRes.data ?? []) as OpenRow[];
  const closed = (closedRes.data ?? []) as ClosedRow[];

  // Open positions per layer.
  const openByLayer: Record<number, number> = {};
  for (const p of open) {
    const l = layerOf(p.asset_type ?? "", p.strategy ?? "");
    openByLayer[l] = (openByLayer[l] ?? 0) + 1;
  }

  // Win rate + avg hold per layer from the last 30 days of closed trades.
  const wins: Record<number, number> = {};
  const tot: Record<number, number> = {};
  const holdSum: Record<number, number> = {};
  for (const c of closed) {
    const l = layerOf(c.asset_type ?? "", c.strategy ?? "");
    tot[l] = (tot[l] ?? 0) + 1;
    if (Number(c.realized_pnl_usd ?? 0) > 0) wins[l] = (wins[l] ?? 0) + 1;
    if (c.entry_at && c.exit_at) {
      const h = (Date.parse(c.exit_at) - Date.parse(c.entry_at)) / 3.6e6;
      if (isFinite(h) && h > 0) holdSum[l] = (holdSum[l] ?? 0) + h;
    }
  }

  const nowMs = Date.now();
  const agents: AGAgent[] = DEFS.map((def) => {
    const layerMsgs = msgs.filter((m) => def.keys.includes(m.agent_name));
    const last = layerMsgs[0];
    const openPositions = openByLayer[def.layer] ?? 0;
    const todayTrades = layerMsgs.filter(
      (m) => (m.kind === "execute" || m.kind === "close") && String(m.created_at).slice(0, 10) === todayKey
    ).length;
    const recent = last ? nowMs - Date.parse(last.created_at) < 90 * 6e4 : false;
    const status = openPositions > 0 || recent ? "active" : "idle";
    const t = tot[def.layer] ?? 0;
    const winRate = t > 0 ? Math.round(((wins[def.layer] ?? 0) / t) * 100) + "%" : "—";
    const avgHold = t > 0 ? fmtHold((holdSum[def.layer] ?? 0) / t) : "—";
    const lastAction = last
      ? describeAgentMessage({
          id: "x",
          agent_name: last.agent_name,
          kind: last.kind,
          payload: last.payload ?? {},
          created_at: last.created_at,
        } as FeedMessage)
      : "No recent activity logged";
    const lastActionTime = last ? String(last.created_at).slice(11, 16) : "—";
    return {
      id: def.id,
      name: def.name,
      layer: def.layer,
      layerName: def.layerName,
      status,
      strategy: def.strategy,
      openPositions,
      todayTrades,
      winRate,
      avgHold,
      lastAction,
      lastActionTime,
      idleReason: status === "idle" ? "No open position and no signal in the last 90 minutes." : undefined,
    };
  });

  const data: AgentsData = { agents, live: true };

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <FadeIn>
        <AgentsViewRedesign data={data} />
      </FadeIn>
    </div>
  );
}
