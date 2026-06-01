import { createClient } from "@/lib/supabase/server";
import { TrimDialog } from "./trim-dialog";

type Alert = {
  id: string;
  ticker: string;
  alert_kind: string;
  severity: "info" | "warn" | "urgent";
  message: string;
  current_price: number | null;
  peak_price: number | null;
  giveback_pct: number | null;
  unrealized_pnl_usd: number | null;
  raised_at: string;
  position_id: string | null;
};

const KIND_LABEL: Record<string, string> = {
  peak_giveback: "Peak giveback",
  stop_approaching: "Stop approaching",
  time_in_trade: "Capital parked",
  trend_break: "Trend break",
  target_hit: "Target hit",
  held_too_long: "Held too long",
  decayed_thesis: "Thesis decayed",
};

/**
 * ExitAdvisorAlerts — surfaces the Exit Advisor's open (unacknowledged)
 * alerts on the Trading page. Designed to be the FIRST thing the user
 * sees when something needs human attention, framed in plain English:
 *
 *   "AAPL hit peak of $812 and has given back 47%. The setup may be
 *   exhausted — consider trimming or trailing the stop."
 *
 * Each card has a "Dismiss" form that sets acknowledged_at, which is
 * what stops the advisor from re-raising the same alert.
 *
 * Renders nothing when there are no open alerts.
 */
export async function ExitAdvisorAlerts() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data: rows } = await supabase
    .from("exit_advisor_alerts")
    .select(
      "id, ticker, alert_kind, severity, message, current_price, peak_price, giveback_pct, unrealized_pnl_usd, raised_at, position_id"
    )
    .eq("user_id", user.id)
    .is("acknowledged_at", null)
    .order("severity", { ascending: false })
    .order("raised_at", { ascending: false })
    .limit(10);

  const alerts = (rows ?? []) as Alert[];
  if (alerts.length === 0) return null;

  return (
    <section className="space-y-2">
      <h2 className="text-xs font-medium uppercase tracking-widest text-weave-500">
        Exit advisor — needs your eyes
      </h2>
      <div className="space-y-2">
        {alerts.map((a) => {
          const tone =
            a.severity === "urgent"
              ? "border-red-200 bg-red-50 text-red-900"
              : a.severity === "warn"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-weave-200 bg-weave-50 text-weave-900";
          return (
            <div
              key={a.id}
              className={`rounded-xl border p-4 ${tone} space-y-2`}
            >
              <div className="flex items-baseline justify-between gap-3 flex-wrap">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono font-medium text-sm">
                    {a.ticker}
                  </span>
                  <span className="text-[10px] uppercase tracking-widest opacity-80">
                    {KIND_LABEL[a.alert_kind] ?? a.alert_kind}
                  </span>
                </div>
                <div className="flex items-baseline gap-3">
                  {/* Trim button only on decayed_thesis alerts with a
                      position to act on. Posts to the trim API which
                      sells 50% of the position at market and frees
                      the capital. Mike 2026-06-01. */}
                  {a.alert_kind === "decayed_thesis" && a.position_id ? (
                    <TrimDialog positionId={a.position_id} />
                  ) : null}
                  <form action="/api/exit-advisor/ack" method="post">
                    <input type="hidden" name="alert_id" value={a.id} />
                    <button
                      type="submit"
                      className="text-[11px] underline opacity-80 hover:opacity-100"
                    >
                      Dismiss
                    </button>
                  </form>
                </div>
              </div>
              <p className="text-sm leading-relaxed">{a.message}</p>
              <div className="flex items-baseline gap-4 text-[11px] font-mono opacity-80 flex-wrap">
                {a.current_price !== null ? (
                  <span>Now ${a.current_price.toFixed(2)}</span>
                ) : null}
                {a.peak_price !== null ? (
                  <span>Peak ${a.peak_price.toFixed(2)}</span>
                ) : null}
                {a.giveback_pct !== null ? (
                  <span>Giveback {(a.giveback_pct * 100).toFixed(0)}%</span>
                ) : null}
                {a.unrealized_pnl_usd !== null ? (
                  <span>Unrealized ${a.unrealized_pnl_usd.toFixed(0)}</span>
                ) : null}
                <span>{new Date(a.raised_at).toLocaleTimeString()}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
