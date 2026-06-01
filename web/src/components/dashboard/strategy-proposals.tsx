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
 * "Recent strategy proposals" — surfaces the moments the agents want
 * to change something. Pulls agent_messages from strategy_discovery +
 * adaptive_scope where the kind is alert / event / metrics so the
 * user sees what was proposed, why, and when. Replaces the "did
 * anything actually change?" guesswork.
 */
export async function StrategyProposalsFeed({ userId }: { userId: string }) {
  const supabase = createClient();
  const { data } = await supabase
    .from("agent_messages")
    .select("id, agent_name, kind, payload, created_at")
    .in("agent_name", ["strategy_discovery", "adaptive_scope"])
    .in("kind", ["alert", "metrics", "info"])
    .or(`user_id.eq.${userId},user_id.is.null`)
    .order("created_at", { ascending: false })
    .limit(15);
  const rows = (data ?? []) as Row[];

  if (rows.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="font-serif text-xl text-weave-800">Recent strategy proposals</h2>
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-500">
          Nothing recorded yet. As the strategy_discovery agent runs
          (hourly) and adaptive_scope reads the market regime (every
          10 min), this feed fills with their proposals — which
          strategy is the strongest performer, when a 25-trade review
          is due, when the regime suggests trimming or pausing a
          strategy family.
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-serif text-xl text-weave-800">
          Recent strategy proposals
        </h2>
        <p className="beginner-only text-sm text-weave-500 leading-relaxed">
          Every time strategy_discovery (hourly) or adaptive_scope
          (every 10 min) wants the bot to favour, trim, pause or flag
          something — it posts here. So you always know what the agents
          are proposing and why.
        </p>
      </div>
      <div className="rounded-xl border border-weave-100 bg-white overflow-hidden">
        <ul className="divide-y divide-weave-50">
          {rows.map((r) => (
            <li key={r.id} className="px-4 py-3 flex items-start gap-3">
              <span
                className={cn(
                  "shrink-0 text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                  r.kind === "alert"
                    ? "bg-amber-100 text-amber-800"
                    : r.kind === "metrics"
                      ? "bg-weave-100 text-weave-700"
                      : "bg-treasure-100 text-treasure-700"
                )}
              >
                {r.agent_name === "adaptive_scope" ? "Scope" : "Discovery"} · {r.kind}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-weave-800 leading-relaxed">
                  {describe(r)}
                </p>
                <p className="text-[11px] text-weave-500 mt-1">
                  {new Date(r.created_at).toLocaleString()}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function describe(r: Row): string {
  const p = r.payload ?? {};
  const ev = String((p as { event?: string }).event ?? "");
  const note = typeof p.note === "string" ? p.note.trim() : "";
  if (ev === "performance_review_due") {
    const trades = Number((p as { total_trades?: number }).total_trades ?? 0);
    return `25-trade performance review due — ${trades} trades logged. The agents have enough sample to evaluate which strategy variants are pulling their weight.`;
  }
  if (note) {
    const bits: string[] = [note];
    const weakest = (p as { weakest_strategy?: string }).weakest_strategy;
    if (weakest) bits.push(`Weakest strategy this window: ${weakest}.`);
    const wr = (p as { win_rate?: number }).win_rate;
    if (typeof wr === "number") bits.push(`Win rate ${(wr * 100).toFixed(0)}%.`);
    return bits.join(" ");
  }
  if (r.agent_name === "strategy_discovery" && r.kind === "metrics") {
    const wr = (p as { win_rate?: number }).win_rate;
    const pf = (p as { profit_factor?: number }).profit_factor;
    return `Performance report — win rate ${typeof wr === "number" ? (wr * 100).toFixed(0) + "%" : "—"}, profit factor ${typeof pf === "number" ? pf.toFixed(2) : "—"}.`;
  }
  return `${r.agent_name} · ${r.kind}`;
}
