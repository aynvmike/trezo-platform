import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

type Row = {
  id: string;
  agent_name: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
};

/**
 * Today's Execution Feed — the agent → Risk Manager → Trade Execution →
 * Alpaca chain for the current calendar day, in one panel. Lets Mike
 * verify the 7-11 AM STMS window (or any window) actually fired and
 * routed to the broker as expected, without hunting through agent_messages.
 *
 * Pulls signal / approve / veto / execute / error rows from today
 * scoped to the signed-in user. Falls back to global rows when nothing
 * has been per-user-tagged yet.
 */
export async function TodaysExecutionFeed({ userId }: { userId: string }) {
  const supabase = createClient();
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);

  const { data: userRows } = await supabase
    .from("agent_messages")
    .select("id, agent_name, kind, payload, created_at")
    .eq("user_id", userId)
    .in("kind", ["signal", "approve", "veto", "execute", "error", "close"])
    .gte("created_at", todayStart.toISOString())
    .order("created_at", { ascending: false })
    .limit(80);

  let rows = (userRows ?? []) as Row[];
  if (rows.length === 0) {
    const { data: globalRows } = await supabase
      .from("agent_messages")
      .select("id, agent_name, kind, payload, created_at")
      .is("user_id", null)
      .in("kind", ["signal", "approve", "veto", "execute", "error", "close"])
      .gte("created_at", todayStart.toISOString())
      .order("created_at", { ascending: false })
      .limit(80);
    rows = (globalRows ?? []) as Row[];
  }

  const byKind = {
    signals: rows.filter((r) => r.kind === "signal").length,
    approved: rows.filter((r) => r.kind === "approve").length,
    vetoed: rows.filter((r) => r.kind === "veto").length,
    executed: rows.filter((r) => r.kind === "execute").length,
    closed: rows.filter((r) => r.kind === "close").length,
    errors: rows.filter((r) => r.kind === "error").length
  };
  const alpacaExecuted = rows.filter(
    (r) =>
      r.kind === "execute" &&
      typeof r.payload === "object" &&
      (r.payload as { broker?: string }).broker === "alpaca"
  ).length;

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Today&apos;s execution feed
          </h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed">
            Every signal a scanner posted today and what happened to it next —
            approved, vetoed, executed at the broker, or closed.
          </p>
        </div>
        <div className="text-[11px] uppercase tracking-widest text-weave-500">
          {byKind.signals} signal · {byKind.approved} approved ·{" "}
          {byKind.executed} executed ({alpacaExecuted} via Alpaca) ·{" "}
          {byKind.vetoed} vetoed · {byKind.errors} error
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-500">
          Nothing has crossed the bus yet today. If you&apos;re inside a
          scanner window (e.g. STMS 7-11 AM ET) and still see nothing,
          force-tick the relevant scanner from the buttons above.
        </div>
      ) : (
        <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Agent</th>
                <th className="px-4 py-3">Kind</th>
                <th className="px-4 py-3">Ticker</th>
                <th className="px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const p = r.payload || {};
                const t = (p as { ticker?: string; underlying?: string }).ticker ||
                  (p as { ticker?: string; underlying?: string }).underlying ||
                  "—";
                const detail = describe(r.kind, p);
                return (
                  <tr key={r.id} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-2.5 text-xs text-weave-500 font-mono whitespace-nowrap">
                      {new Date(r.created_at).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-weave-600">
                      {r.agent_name.replace(/_/g, " ")}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={cn("text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5", kindColor(r.kind))}>
                        {r.kind}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
                      {t}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-weave-600">
                      {detail}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function kindColor(kind: string): string {
  if (kind === "execute") return "bg-emerald-100 text-emerald-800";
  if (kind === "approve") return "bg-emerald-50 text-emerald-700";
  if (kind === "veto") return "bg-amber-100 text-amber-800";
  if (kind === "close") return "bg-weave-100 text-weave-700";
  if (kind === "error") return "bg-red-100 text-red-700";
  return "bg-weave-50 text-weave-500";
}

// Phase E: pull a one-line memory-driven hint from learning_context
// when present. Risk Manager + Options Scanner attach this to every
// approve / wheel_suggestion. Empty string when absent.
function learningHint(p: Record<string, unknown>): string {
  const lc = (p as { learning_context?: { available?: boolean; summary?: string } })
    .learning_context;
  if (!lc || lc.available === false) return "";
  return lc.summary || "";
}

function describe(kind: string, p: Record<string, unknown>): string {
  if (kind === "signal") {
    const tcs = (p as { tcs?: number }).tcs;
    const strat = (p as { strategy?: string }).strategy;
    const dir = (p as { direction?: string }).direction;
    return [
      tcs !== undefined ? `TCS ${tcs}` : null,
      strat ? `strategy=${strat}` : null,
      dir ? dir : null
    ]
      .filter(Boolean)
      .join(" · ");
  }
  if (kind === "approve") {
    const base = (p as { note?: string }).note || "approved by Risk Manager";
    const hint = learningHint(p);
    return hint ? `${base} · ${hint}` : base;
  }
  if (kind === "veto") {
    return (p as { reason?: string; note?: string }).reason ||
      (p as { note?: string }).note ||
      "blocked by Risk Manager";
  }
  if (kind === "execute") {
    const broker = (p as { broker?: string }).broker;
    const order = (p as { alpaca_order_id?: string }).alpaca_order_id;
    const status = (p as { alpaca_order_status?: string }).alpaca_order_status;
    const fill = (p as { fill_price?: number }).fill_price;
    const qty = (p as { quantity?: number }).quantity;
    return [
      broker ? `broker=${broker}` : null,
      qty ? `qty ${qty}` : null,
      fill ? `@$${Number(fill).toFixed(2)}` : null,
      order ? `order ${String(order).slice(0, 8)}…` : null,
      status ? status : null
    ]
      .filter(Boolean)
      .join(" · ");
  }
  if (kind === "close") {
    const reason = (p as { reason?: string }).reason;
    const pnl = (p as { realized_pnl_usd?: number; pnl_usd?: number }).realized_pnl_usd ??
      (p as { pnl_usd?: number }).pnl_usd;
    return [reason, pnl !== undefined ? `pnl=$${Number(pnl).toFixed(2)}` : null]
      .filter(Boolean)
      .join(" · ");
  }
  if (kind === "error") {
    return (p as { error?: string }).error || "error";
  }
  // info rows — covers wheel_suggestion / options_idea / filtered emits
  // from the Options Scanner. Surface the event + bucket + learning hint.
  if (kind === "info") {
    const event = (p as { event?: string }).event;
    const bucket = (p as { bucket?: string }).bucket;
    const note = (p as { note?: string }).note;
    if (event) {
      const hint = learningHint(p);
      const parts: (string | null | undefined)[] = [
        event.replace(/_/g, " "),
        bucket ? `bucket=${bucket}` : null,
        note,
        hint || null,
      ];
      return parts.filter(Boolean).join(" · ");
    }
    return note || JSON.stringify(p).slice(0, 80);
  }
  return JSON.stringify(p).slice(0, 80);
}
