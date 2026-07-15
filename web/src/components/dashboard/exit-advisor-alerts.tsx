import { createClient } from "@/lib/supabase/server";
import { TrimDialog } from "./trim-dialog";
import { OptionsTrimButton } from "./options-trim-button";

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
  // Stock-side (existing Exit Advisor)
  peak_giveback: "Peak giveback",
  stop_approaching: "Stop approaching",
  time_in_trade: "Capital parked",
  trend_break: "Trend break",
  target_hit: "Target hit",
  held_too_long: "Held too long",
  decayed_thesis: "Thesis decayed",
  // Options-side (Phase B / D — ExitAdvisorOptionsAgent)
  drawdown_tolerance_hit: "Drawdown ceiling hit",
  save_profit_before_negative: "Save profit",
  defensive_trim: "Defensive trim",
  trim_for_capital_recovery: "Capital recovery",
  profit_target_low_tier: "Profit target (low contracts)",
  emotion_cap_take_gain: "Emotion cap (high contracts)",
  hopeful_near_cap: "Hopeful bucket near cap",
};

// Options-specific alert kinds — used to swap UI affordances (no
// stock TrimDialog for options, show an "Options" badge, use the
// OptionsTrimButton instead).
const OPTIONS_KINDS = new Set([
  "drawdown_tolerance_hit",
  "save_profit_before_negative",
  "defensive_trim",
  "trim_for_capital_recovery",
  "profit_target_low_tier",
  "emotion_cap_take_gain",
  "hopeful_near_cap",
]);

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
    <section
      className={
        // Mike 2026-07-15: the alert stack was pushing the Trading page a
        // full screen down. On wide displays it now FLOATS as a pinned,
        // scrollable card on the right rail (sharing the "what's
        // happening" role with the activity ticker); on smaller screens
        // it stays inline but scrolls INSIDE a capped card instead of
        // growing the page.
        "space-y-2 " +
        "min-[1900px]:fixed min-[1900px]:right-5 min-[1900px]:top-24 " +
        "min-[1900px]:w-[350px] min-[1900px]:z-40 min-[1900px]:rounded-2xl " +
        "min-[1900px]:border min-[1900px]:border-weave-200 " +
        "min-[1900px]:bg-white/95 min-[1900px]:backdrop-blur " +
        "min-[1900px]:shadow-lg min-[1900px]:p-3"
      }
    >
      <h2 className="text-xs font-medium uppercase tracking-widest text-weave-500">
        Exit advisor — needs your eyes ({alerts.length})
      </h2>
      <div className="space-y-2 max-h-[38vh] min-[1900px]:max-h-[64vh] overflow-y-auto pr-1">
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
                  {OPTIONS_KINDS.has(a.alert_kind) ? (
                    <span className="text-[9px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-700 px-1.5 py-0.5 font-medium">
                      Options
                    </span>
                  ) : null}
                </div>
                <div className="flex items-baseline gap-3">
                  {/* Stock trim - decayed_thesis only. */}
                  {a.alert_kind === "decayed_thesis"
                    && a.position_id
                    && !OPTIONS_KINDS.has(a.alert_kind) ? (
                    <TrimDialog positionId={a.position_id} />
                  ) : null}
                  {/* Options trim - on any options alert kind with a
                      specific position. hopeful_near_cap is bucket-level
                      so excluded. Task #29. */}
                  {OPTIONS_KINDS.has(a.alert_kind)
                    && a.alert_kind !== "hopeful_near_cap"
                    && a.position_id ? (
                    <OptionsTrimButton positionId={a.position_id} />
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
                  <span>
                    {OPTIONS_KINDS.has(a.alert_kind) ? "Mark" : "Now"} $
                    {a.current_price.toFixed(2)}
                  </span>
                ) : null}
                {a.peak_price !== null ? (
                  <span>Peak ${a.peak_price.toFixed(2)}</span>
                ) : null}
                {a.giveback_pct !== null ? (
                  <span>
                    {OPTIONS_KINDS.has(a.alert_kind) ? "Drawback" : "Giveback"}{" "}
                    {(a.giveback_pct * 100).toFixed(0)}%
                  </span>
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
