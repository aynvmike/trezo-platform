import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

type Row = {
  id: string;
  agent_name: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type Trace = {
  ticker: string;
  signal_at: string;
  tcs?: number;
  direction?: string;
  strategy?: string;
  outcome: "executed" | "vetoed" | "skipped" | "pending" | "error";
  outcome_label: string;
  outcome_reason: string;
  broker?: string;
  order_id?: string;
};

/**
 * Signal trace panel — pairs each signal that fired in the last hour
 * with what happened to it downstream (Risk Manager veto, Trade
 * Execution budget skip, Alpaca order id). Answers "the scanner fired
 * 19 signals, why didn't I get 19 trades" in one view.
 */
export async function SignalTracePanel({ userId }: { userId: string }) {
  const supabase = createClient();
  const hourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();

  // Pull every relevant message from the last hour for this user (with
  // a global fallback for messages that haven't been per-user-tagged).
  const fetchRows = async (forUser: boolean) => {
    let q = supabase
      .from("agent_messages")
      .select("id, agent_name, kind, payload, created_at")
      .in("kind", ["signal", "approve", "veto", "execute", "error", "info"])
      .gte("created_at", hourAgo)
      .order("created_at", { ascending: true })
      .limit(500);
    q = forUser ? q.eq("user_id", userId) : q.is("user_id", null);
    const { data } = await q;
    return (data ?? []) as Row[];
  };

  let rows = await fetchRows(true);
  if (rows.length === 0) rows = await fetchRows(false);

  // Group by ticker → newest signal wins; then look at any veto / execute
  // / info row after that signal for the same ticker as the fate.
  const signalsByTicker: Map<string, Row> = new Map();
  for (const r of rows) {
    if (r.kind !== "signal") continue;
    const t = String((r.payload as { ticker?: string }).ticker ?? "").toUpperCase();
    if (!t) continue;
    signalsByTicker.set(t, r); // last one wins (rows are oldest→newest)
  }

  const traces: Trace[] = [];
  signalsByTicker.forEach((sigRow, ticker) => {
    const sigAt = new Date(sigRow.created_at).getTime();
    const p = sigRow.payload as Record<string, unknown>;
    const downstream = rows.filter((r) => {
      if (new Date(r.created_at).getTime() < sigAt) return false;
      const t = String((r.payload as { ticker?: string }).ticker ?? "").toUpperCase();
      return t === ticker && r.kind !== "signal";
    });
    const exec = downstream.find((d) => d.kind === "execute");
    const veto = downstream.find((d) => d.kind === "veto");
    const err = downstream.find((d) => d.kind === "error");
    const info = downstream.find((d) => {
      const n = String((d.payload as { note?: string }).note ?? "").toLowerCase();
      return d.kind === "info" &&
        (n.includes("budget") || n.includes("skipped") || n.includes("market closed") || n.includes("already"));
    });

    let outcome: Trace["outcome"] = "pending";
    let outcome_label = "Pending downstream";
    let outcome_reason = "Risk Manager hasn't processed this signal yet.";
    let broker: string | undefined;
    let order_id: string | undefined;
    if (exec) {
      outcome = "executed";
      outcome_label = "Executed";
      const ep = exec.payload as Record<string, unknown>;
      broker = (ep.broker as string) ?? (ep.venue as string);
      order_id = (ep.alpaca_order_id as string) ?? (ep.position_id as string);
      const qty = ep.quantity;
      const fp = ep.fill_price;
      outcome_reason = `${broker ?? "?"} · ${qty ?? "?"} @ $${typeof fp === "number" ? fp.toFixed(2) : "?"}`;
    } else if (veto) {
      outcome = "vetoed";
      outcome_label = "Vetoed by Risk Manager";
      outcome_reason = String((veto.payload as { reason?: string }).reason ?? "(no reason)");
    } else if (info) {
      outcome = "skipped";
      outcome_label = "Skipped (gate)";
      outcome_reason = String((info.payload as { note?: string }).note ?? "(no detail)");
    } else if (err) {
      outcome = "error";
      outcome_label = "Errored";
      outcome_reason = String((err.payload as { error?: string }).error ?? "(no detail)");
    }

    traces.push({
      ticker,
      signal_at: sigRow.created_at,
      tcs: p.tcs as number | undefined,
      direction: p.direction as string | undefined,
      strategy: p.strategy as string | undefined,
      outcome,
      outcome_label,
      outcome_reason,
      broker,
      order_id
    });
  });

  // Newest signals on top.
  traces.sort((a, b) => new Date(b.signal_at).getTime() - new Date(a.signal_at).getTime());

  const counts = {
    total: traces.length,
    executed: traces.filter((t) => t.outcome === "executed").length,
    vetoed: traces.filter((t) => t.outcome === "vetoed").length,
    skipped: traces.filter((t) => t.outcome === "skipped").length,
    pending: traces.filter((t) => t.outcome === "pending").length
  };

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">Signal trace · last hour</h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
            Every signal that fired in the last hour paired with what
            happened to it downstream. Shows you why a tick&apos;s 19
            signals can result in only 1–2 actual orders — Risk
            Manager vetoes some, Trade Execution skips others (already
            open, budget gate, market closed), and only the ones that
            survive both make it to the broker.
          </p>
        </div>
        <span className="text-[11px] uppercase tracking-widest text-weave-500">
          {counts.total} signal · {counts.executed} executed · {counts.vetoed} vetoed · {counts.skipped} skipped · {counts.pending} pending
        </span>
      </div>
      {traces.length === 0 ? (
        <div className="rounded-lg border border-dashed border-weave-200 bg-treasure-100/40 p-4 text-sm text-weave-500">
          No signals in the last hour. If a scanner window is open and
          this is still empty, the TCS threshold is filtering everything
          out — try lowering it in Bot Tuning.
        </div>
      ) : (
        <div className="rounded-lg border border-weave-100 overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-4 py-2.5">Ticker</th>
                <th className="px-4 py-2.5">TCS</th>
                <th className="px-4 py-2.5">Direction</th>
                <th className="px-4 py-2.5">Strategy</th>
                <th className="px-4 py-2.5">Fate</th>
                <th className="px-4 py-2.5">Reason / detail</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => (
                <tr key={`${t.ticker}-${t.signal_at}`} className="border-b border-weave-50 last:border-0">
                  <td className="px-4 py-2 font-mono font-medium text-weave-800">{t.ticker}</td>
                  <td className="px-4 py-2 font-mono text-xs text-weave-700">{t.tcs ?? "—"}</td>
                  <td className="px-4 py-2 text-xs text-weave-600">{t.direction ?? "—"}</td>
                  <td className="px-4 py-2 text-xs text-weave-600">{t.strategy ?? "—"}</td>
                  <td className="px-4 py-2">
                    <span className={cn(
                      "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                      t.outcome === "executed" && "bg-emerald-100 text-emerald-800",
                      t.outcome === "vetoed" && "bg-amber-100 text-amber-800",
                      t.outcome === "skipped" && "bg-weave-100 text-weave-700",
                      t.outcome === "pending" && "bg-weave-50 text-weave-500",
                      t.outcome === "error" && "bg-red-100 text-red-700"
                    )}>
                      {t.outcome_label}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-weave-600">{t.outcome_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
