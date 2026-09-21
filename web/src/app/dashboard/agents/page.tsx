import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { FadeIn } from "@/components/dashboard/fade-in";
import {
  AgentsViewRedesign,
  type AgentsData,
  type AGAgent,
} from "@/components/dashboard/agents-view-redesign";
import { AgentsSettings } from "./_agents-settings";
import { describeAgentMessage, type FeedMessage } from "@/lib/agent-message";
import { LoadErrors, loadResult, failuresOf } from "@/components/dashboard/load-error";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";
import Link from "next/link";
import { BookCapabilitiesPanel } from "@/components/dashboard/book-capabilities-panel";
import { ActivityFeed } from "@/components/dashboard/activity-feed";
import { messageBelongsToBooks } from "@/lib/agent-book-scope";

export const dynamic = "force-dynamic";

type Memory = { agent: string; category: string; content: string; weight: number; updated_at: string };
type MsgRow = { user_id: string | null; agent_name: string; kind: string; payload: Record<string, unknown> | null; created_at: string };
type OpenRow = { ticker?: string; asset_type: string | null; strategy: string | null };
type ClosedRow = { realized_pnl_usd: number | null; entry_at: string | null; exit_at: string | null; asset_type: string | null; strategy: string | null };
type OptionRow = { underlying: string; strategy: string; strike: number | null; expiration: string | null; option_type: string; opened_at: string | null; closed_at: string | null; realized_pnl_usd: number | null };

function optionSymbol(row: OptionRow): string {
  if (!row.expiration || row.strike == null) return "";
  return `${row.underlying}${row.expiration.slice(2, 10).replace(/-/g, "")}${row.option_type === "put" ? "P" : "C"}${String(Math.round(Number(row.strike) * 1000)).padStart(8, "0")}`.toUpperCase();
}

const DEFS: { id: number; name: string; layer: number; layerName: string; strategy: string; keys: string[] }[] = [
  { id: 1, name: "Crypto Bot", layer: 1, layerName: "Crypto", strategy: "Momentum + RSI reversal on crypto", keys: ["crypto_scanner"] },
  { id: 2, name: "Stock Bot", layer: 2, layerName: "Stock", strategy: "Breakout + pullback on the daily trend", keys: ["stms_scanner", "orb_scanner", "pattern_detection"] },
  { id: 3, name: "Options Bot", layer: 3, layerName: "Options", strategy: "Calls, puts and defined-risk bullish / bearish spreads", keys: ["options_scanner"] },
  { id: 4, name: "Extended Bot", layer: 4, layerName: "Extended", strategy: "Multi-day swings and events", keys: ["extended_scanner"] },
  { id: 5, name: "Wheel Bot", layer: 5, layerName: "Wheel", strategy: "Cash-secured puts into covered calls", keys: ["options_scanner"] },
  { id: 6, name: "Dividends Bot", layer: 6, layerName: "Dividends", strategy: "High-yield dividend capture", keys: ["dividend_manager"] },
  { id: 7, name: "KINDRIP Bot", layer: 7, layerName: "KINDRIP", strategy: "Long-only kind and responsible ETFs", keys: ["kindrip"] },
];

function layerOf(assetType: string, strategy: string): number {
  const a = (assetType || "").toLowerCase();
  const s = (strategy || "").toLowerCase();
  if (s.startsWith("wheel") || s === "dividend_wheel") return 5;
  if (s.includes("dividend") || s.includes("yieldmax")) return 6;
  if (s.startsWith("kindrip")) return 7;
  if (s.startsWith("extended")) return 4;
  if (a === "crypto") return 1;
  if (a === "option" || a === "options") return 3;
  return 2;
}
function fmtHold(hours: number): string {
  if (!isFinite(hours) || hours <= 0) return "—";
  return hours < 24 ? hours.toFixed(1) + "h" : (hours / 24).toFixed(1) + "d";
}

export default async function AgentsPage({ searchParams }: { searchParams?: { account?: string } }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/agents");

  const dayIso = new Date(Date.now() - 1 * 864e5).toISOString();
  const monthIso = new Date(Date.now() - 30 * 864e5).toISOString();
  const todayKey = new Date().toISOString().slice(0, 10);

  // rv:web-pages sweep: paper_positions is keyed by BOOK (0047); read
  // across every book the person owns, not just the one whose key
  // equals the auth uid.
  const booksLoad = await getOwnerBookKeys(supabase, user.id);
  const { data: accountRows } = await supabase.from("trading_accounts")
    .select("account_key, label").eq("owner_id", user.id).eq("is_active", true).order("label");
  const books = accountRows ?? [];
  const requested = searchParams?.account;
  const activeKey = requested && booksLoad.data?.includes(requested) ? requested
    : requested ? undefined : books[0]?.account_key;
  const keys = bookQueryKeys(activeKey ? [String(activeKey)] : []);
  const activeBook = books.find((book) => book.account_key === activeKey);

  const [msgsRes, openRes, closedRes, optionsOpenRes, optionsClosedRes, memRes] = await Promise.all([
    supabase.from("agent_messages").select("user_id, agent_name, kind, payload, created_at")
      .or(`user_id.in.(${[...new Set([...(booksLoad.data ?? []), user.id])].join(",")}),user_id.is.null`).gte("created_at", dayIso)
      .order("created_at", { ascending: false }).limit(150),
    supabase.from("paper_positions").select("ticker, asset_type, strategy").in("user_id", keys).eq("status", "open"),
    supabase.from("paper_positions").select("realized_pnl_usd, entry_at, exit_at, asset_type, strategy")
      .in("user_id", keys).neq("status", "open").gte("exit_at", monthIso),
    supabase.from("options_positions").select("underlying, strategy, strike, expiration, option_type, opened_at, closed_at, realized_pnl_usd")
      .in("user_id", keys).eq("status", "open"),
    supabase.from("options_positions").select("underlying, strategy, strike, expiration, option_type, opened_at, closed_at, realized_pnl_usd")
      .in("user_id", keys).neq("status", "open").gte("closed_at", monthIso),
    supabase.from("agent_memory").select("agent, category, content, weight, updated_at")
      .eq("scope", "shared").order("weight", { ascending: false }).order("updated_at", { ascending: false }).limit(12),
  ]);

  // PAGES-03: keep "read failed" distinct from "nothing there". The
  // board's status/win-rate/hold numbers are derived from the first
  // three reads, so if any of them failed the board is not shown —
  // every agent would otherwise read as "idle, 0 trades".
  const msgsLoad = loadResult<MsgRow[]>("agent_messages", msgsRes, []);
  const openLoad = loadResult<OpenRow[]>("paper_positions", openRes, []);
  const closedLoad = loadResult<ClosedRow[]>("paper_positions (closed)", closedRes, []);
  const memLoad = loadResult<Memory[]>("agent_memory", memRes, []);
  const optionsOpenLoad = loadResult<OptionRow[]>("options_positions", optionsOpenRes, []);
  const optionsClosedLoad = loadResult<OptionRow[]>("options_positions (closed)", optionsClosedRes, []);
  const boardFailures = failuresOf(booksLoad, msgsLoad, openLoad, closedLoad, optionsOpenLoad, optionsClosedLoad);
  const msgs = (msgsLoad.data ?? []).filter((message) => activeKey && messageBelongsToBooks(message, booksLoad.data ?? [], user.id, String(activeKey)));
  const ledgerSymbols = new Set((openLoad.data ?? []).map((position) => String(position.ticker ?? "").toUpperCase()));
  const open = [...(openLoad.data ?? []), ...(optionsOpenLoad.data ?? [])
    .filter((option) => !ledgerSymbols.has(optionSymbol(option)))
    .map((option) => ({ asset_type: "option", strategy: option.strategy }))];
  const closed = [...(closedLoad.data ?? []), ...(optionsClosedLoad.data ?? [])
    .map((option) => ({ asset_type: "option", strategy: option.strategy, realized_pnl_usd: option.realized_pnl_usd, entry_at: option.opened_at, exit_at: option.closed_at }))];
  const learned = memLoad.data ?? [];

  const openByLayer: Record<number, number> = {};
  for (const p of open) {
    const l = layerOf(p.asset_type ?? "", p.strategy ?? "");
    openByLayer[l] = (openByLayer[l] ?? 0) + 1;
  }
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
    const layerMsgs = msgs.filter((m) => {
      if (!def.keys.includes(m.agent_name)) return false;
      const wheel = [m.payload?.strategy, m.payload?.event, m.payload?.lane]
        .some((value) => String(value ?? "").toLowerCase().startsWith("wheel"));
      return def.layer === 5 ? wheel : def.layer === 3 ? !wheel : true;
    });
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
      ? describeAgentMessage({ id: "x", agent_name: last.agent_name, kind: last.kind, payload: last.payload ?? {}, created_at: last.created_at } as FeedMessage)
      : "No recent activity logged";
    const lastActionTime = last ? String(last.created_at).slice(11, 16) : "—";
    return {
      id: def.id, name: def.name, layer: def.layer, layerName: def.layerName, status,
      strategy: def.strategy, openPositions, todayTrades, winRate, avgHold, lastAction, lastActionTime,
      idleReason: status === "idle" ? "No open position and no signal in the last 90 minutes." : undefined,
    };
  });

  const data: AgentsData = { agents, live: true };

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 space-y-8">
      <div className="space-y-3">
        <h1 className="font-serif text-2xl text-weave-800">Agents by account</h1>
        <p className="text-sm text-weave-500">Select a book to see its positions, performance and activity. Each book uses its own trading settings.</p>
        <nav className="flex flex-wrap gap-2" aria-label="Trading account">
          {books.map((book) => <Link key={book.account_key} href={`/dashboard/agents?account=${encodeURIComponent(book.account_key)}`} aria-current={book.account_key === activeKey ? "page" : undefined} className={cn("rounded-lg border px-3 py-2 text-sm", book.account_key === activeKey ? "border-emerald-400 bg-emerald-50 text-emerald-900" : "border-weave-200 text-weave-700")}>{book.label ?? "Account"}</Link>)}
        </nav>
        {!activeKey && <p role="alert" className="text-sm text-amber-800">{requested ? "That active account is unavailable. Select one of your accounts." : "No active account is available."}</p>}
      </div>
      <LoadErrors failures={failuresOf(memLoad)} />
      {boardFailures.length > 0 ? (
        <LoadErrors failures={boardFailures} />
      ) : activeKey ? (
        <FadeIn>
          <AgentsViewRedesign data={data} />
        </FadeIn>
      ) : null}

      <BookCapabilitiesPanel accountKey={activeKey ? String(activeKey) : undefined} />
      {activeKey && <section className="space-y-3">
        <h2 className="font-serif text-xl text-weave-800">{activeBook?.label ?? "Account"} activity</h2>
        <ActivityFeed key={String(activeKey)} accountKey={String(activeKey)} limit={80} />
      </section>}

      <section className="space-y-3">
        <div>
          <h2 className="font-serif text-xl text-[rgb(var(--foreground))]">Manage agents</h2>
          <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">Service controls affect shared workers across all books. Use &ldquo;Tune this book&rdquo; to change one account's strategy permissions.</p>
        </div>
        <AgentsSettings />
      </section>

      {learned.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="font-serif text-xl text-weave-800">What the agents have learned</h2>
            <p className="mt-1 max-w-2xl text-sm text-weave-500 leading-relaxed">
              Shared, evolving memory — durable insight the agents keep and build on across runs. A heavier weight (×) means an observation reinforced over time.
            </p>
          </div>
          <div className="space-y-2">
            {learned.map((m, i) => (
              <div key={i} className="rounded-xl border border-weave-100 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-weave-500">{m.agent}</span>
                  <div className="flex items-center gap-2">
                    <span className={cn("text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5", m.category === "warning" ? "bg-amber-100 text-amber-800" : "bg-weave-50 text-weave-600")}>{m.category}</span>
                    <span className="text-[10px] text-weave-400" title="Reinforcement weight">×{Number(m.weight).toFixed(0)}</span>
                  </div>
                </div>
                <p className="mt-1.5 text-sm text-weave-700 leading-relaxed">{m.content}</p>
                <p className="mt-1 text-[10px] text-weave-400">{new Date(m.updated_at).toLocaleString()}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
