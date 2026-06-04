import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

/**
 * WheelAcquisitionQueue — replaces the "Modeled wheel planner —
 * where each name would be" example grid (Mike 2026-06-03).
 *
 * Shows only what the bot is ACTIVELY queueing for acquisition:
 *  - Pulls today's `wheel_suggestion` events from agent_messages
 *  - One card per underlying (most recent suggestion wins)
 *  - Surfaces credit, strike, expiration, modeled IV, projected yield,
 *    plus a "why this name now" reasoning line
 *
 * When empty (after hours or fresh restart), explains when the bot
 * will populate it instead of showing 17 generic example cards.
 */

type WheelSuggestion = {
  user_id: string;
  underlying: string;
  strategy: string;
  credit_usd: number;
  strike: number;
  expiration: string;
  modeled?: boolean;
  note?: string;
  options_scanner_memory_id?: string | null;
  learning_context?: {
    available?: boolean;
    summary?: string;
    n_outcomes?: number;
    wins?: number;
    losses?: number;
  };
};

type Row = {
  id: string;
  payload: WheelSuggestion & { event?: string };
  created_at: string;
};

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return String(iso);
  }
}

function dteFromExp(exp: string | null | undefined): number | null {
  if (!exp) return null;
  try {
    const d = new Date(`${exp.slice(0, 10)}T16:00:00Z`).getTime();
    const ms = d - Date.now();
    return Math.round(ms / (1000 * 60 * 60 * 24));
  } catch {
    return null;
  }
}

export async function WheelAcquisitionQueue() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  // Last 24h of wheel_suggestion events, this user only.
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const { data } = await supabase
    .from("agent_messages")
    .select("id, payload, created_at")
    .eq("agent_name", "options_scanner")
    .eq("kind", "info")
    .gte("created_at", since)
    .order("created_at", { ascending: false })
    .limit(200);

  const rows = (data ?? []) as Row[];

  // Filter to wheel_suggestion events for THIS user and dedupe by underlying.
  const byTicker = new Map<string, Row>();
  for (const r of rows) {
    const p = r.payload || ({} as WheelSuggestion & { event?: string });
    if (p.event !== "wheel_suggestion") continue;
    if (p.user_id && p.user_id !== user.id) continue;
    const key = (p.underlying || "").toUpperCase();
    if (!key) continue;
    if (!byTicker.has(key)) byTicker.set(key, r);
  }

  const queue = Array.from(byTicker.values());

  return (
    <section>
      <header className="mb-3">
        <h2 className="font-serif text-xl text-weave-800">
          Acquisition queue{" "}
          <span className="text-sm text-weave-500">({queue.length})</span>
        </h2>
        <p className="mt-1 text-sm text-weave-500 leading-relaxed">
          Names the Options Scanner has queued for cash-secured puts in the
          last 24 hours. Replaces the old &ldquo;every example&rdquo; grid —
          only what the bot is actually planning to acquire.
        </p>
      </header>

      {queue.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-600 leading-relaxed text-center">
          <p className="font-medium">Queue is empty right now.</p>
          <p className="mt-1 text-weave-500">
            The Options Scanner ticks every 30 minutes during the US session.
            When it finds a Wheel name that clears your Greek filters,
            it appears here with the credit, strike, expiration, and the
            reasoning behind the pick.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {queue.map((r) => {
            const p = r.payload as WheelSuggestion;
            const credit = Number(p.credit_usd ?? 0);
            const strike = Number(p.strike ?? 0);
            const collateral = strike * 100;
            const yieldPct =
              collateral > 0 ? (credit / collateral) * 100 : null;
            const dte = dteFromExp(p.expiration);
            const dteTone =
              dte === null
                ? "text-weave-500"
                : dte <= 7
                ? "text-red-700"
                : dte <= 21
                ? "text-amber-700"
                : "text-weave-700";
            const isCC = p.strategy === "wheel_cc";
            const direction = isCC ? "Sell call (covered)" : "Sell put (CSP)";
            const lc = p.learning_context;
            return (
              <div
                key={r.id}
                className="rounded-xl border border-weave-100 bg-white p-4 space-y-2.5"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="font-mono font-medium text-base text-weave-800">
                    {p.underlying}
                  </h3>
                  <span className="text-[10px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-800 px-2 py-0.5 font-medium">
                    {isCC ? "CC" : "CSP"}
                  </span>
                </div>

                <p className="text-xs text-weave-600 leading-relaxed">
                  <span className="font-medium">Direction:</span> {direction}
                </p>

                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-weave-500">
                      Credit
                    </p>
                    <p className="font-mono text-emerald-700 font-medium">
                      {fmtUsd(credit)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-weave-500">
                      Strike
                    </p>
                    <p className="font-mono text-weave-800">
                      {fmtUsd(strike)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-weave-500">
                      DTE
                    </p>
                    <p className={cn("font-mono", dteTone)}>
                      {dte !== null ? `${dte}d` : "—"}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-weave-500">
                      Yield (premium / collateral)
                    </p>
                    <p className="font-mono text-weave-800">
                      {yieldPct !== null ? `${yieldPct.toFixed(2)}%` : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-weave-500">
                      Expires
                    </p>
                    <p className="font-mono text-weave-700">
                      {fmtDate(p.expiration)}
                    </p>
                  </div>
                </div>

                {p.note ? (
                  <p className="text-xs text-weave-600 leading-relaxed border-l-2 border-treasure-200 pl-2">
                    <span className="text-[10px] uppercase tracking-widest text-treasure-700 font-medium">
                      Why:
                    </span>{" "}
                    {p.note}
                  </p>
                ) : null}

                {lc && lc.available && lc.summary ? (
                  <p className="text-[11px] text-weave-500 italic leading-relaxed">
                    <span className="text-treasure-700 not-italic">
                      Memory:
                    </span>{" "}
                    {lc.summary}
                  </p>
                ) : null}

                <p className="text-[10px] text-weave-400 font-mono">
                  Queued {new Date(r.created_at).toLocaleTimeString()}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
