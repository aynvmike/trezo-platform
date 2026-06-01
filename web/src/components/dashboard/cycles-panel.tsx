import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

type CyclePosition = {
  next_earnings_date?: string | null;
  days_until_earnings?: number | null;
  earnings_time?: string | null;
  next_exdiv_date?: string | null;
  days_until_exdiv?: number | null;
  next_dividend_amount?: number | null;
  iv_environment?: string;
};

type CyclePayload = {
  note?: string;
  positions?: Record<string, CyclePosition>;
  summary_lines?: string[];
};

/**
 * "Upcoming cycles" panel — reads the latest Cycle Awareness agent
 * message and renders the most notable upcoming events as compact
 * cards. Mike's "think like a human" Phase 13a push: the bot already
 * sees these cycles internally; this surface makes them visible.
 */
export async function CyclesPanel({ userId }: { userId: string }) {
  const supabase = createClient();

  // Most recent CycleAwarenessAgent message for this user. Fall back
  // to the global digest (user_id IS NULL) when no per-user message
  // has landed yet.
  const { data: rows } = await supabase
    .from("agent_messages")
    .select("payload, created_at")
    .eq("agent_name", "cycle_awareness")
    .eq("kind", "info")
    .order("created_at", { ascending: false })
    .limit(20);

  let payload: CyclePayload | null = null;
  for (const r of rows ?? []) {
    const p = (r.payload ?? {}) as CyclePayload & { user_id?: string };
    if ((p as { user_id?: string }).user_id === userId) {
      payload = p;
      break;
    }
  }
  if (!payload) {
    for (const r of rows ?? []) {
      const p = (r.payload ?? {}) as CyclePayload & { user_id?: string };
      if (!(p as { user_id?: string }).user_id) {
        payload = p;
        break;
      }
    }
  }

  if (!payload || !payload.positions) return null;

  // Filter to the notable subset (anything ≤ 14 days out for earnings
  // OR within the dividend window).
  const positions = Object.entries(payload.positions)
    .map(([sym, p]) => ({ sym, p }))
    .filter(({ p }) => {
      const e = p.days_until_earnings;
      const d = p.days_until_exdiv;
      if (typeof e === "number" && e >= -3 && e <= 14) return true;
      if (typeof d === "number" && d >= -2 && d <= 7) return true;
      return false;
    })
    .sort((a, b) => {
      const ea = a.p.days_until_earnings ?? 999;
      const eb = b.p.days_until_earnings ?? 999;
      return ea - eb;
    });

  if (positions.length === 0) return null;

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Upcoming cycles
          </h2>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed mt-1">
            Earnings + ex-dividend dates for the next two weeks across
            your watchlist. The bot reads these too — signals close to
            earnings get a higher TCS bar; the Wheel reads the dividend
            window when picking covered calls.
          </p>
        </div>
        <p className="text-[11px] uppercase tracking-widest text-weave-500">
          Refreshed every 6h
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {positions.map(({ sym, p }) => (
          <CycleCard key={sym} sym={sym} p={p} />
        ))}
      </div>

      {payload.note && (
        <p className="text-[11px] text-weave-500 leading-relaxed pt-2 border-t border-weave-50">
          {payload.note}
        </p>
      )}
      <p className="text-[10px] text-weave-400 leading-relaxed">
        Cycle data via Finnhub.
      </p>
    </section>
  );
}

function CycleCard({ sym, p }: { sym: string; p: CyclePosition }) {
  const env = p.iv_environment ?? "normal";
  const tone =
    env === "earnings_day"
      ? "border-red-200 bg-red-50 text-red-900"
      : env === "high"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : env === "post_earnings"
          ? "border-weave-200 bg-weave-50 text-weave-700"
          : env === "dividend_window"
            ? "border-treasure-200 bg-treasure-50 text-treasure-900"
            : "border-weave-100 bg-weave-50/40 text-weave-700";

  const tagText =
    env === "earnings_day"
      ? "EARNINGS TODAY"
      : env === "high"
        ? "PRE-EARNINGS"
        : env === "post_earnings"
          ? "POST-EARNINGS"
          : env === "dividend_window"
            ? "EX-DIV WINDOW"
            : "NORMAL";

  return (
    <div className={cn("rounded-lg border p-3", tone)}>
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <p className="font-mono font-medium text-sm">{sym}</p>
        <span className="text-[9px] uppercase tracking-widest rounded-full px-1.5 py-0.5 bg-white/60">
          {tagText}
        </span>
      </div>
      <ul className="mt-2 text-[11px] leading-relaxed space-y-0.5 opacity-90">
        {typeof p.days_until_earnings === "number" && (
          <li>
            Earnings:{" "}
            <span className="font-mono">
              {p.next_earnings_date}{" "}
              {p.earnings_time === "bmo"
                ? "(pre)"
                : p.earnings_time === "amc"
                  ? "(post)"
                  : ""}
            </span>{" "}
            ·{" "}
            {p.days_until_earnings === 0
              ? "today"
              : p.days_until_earnings > 0
                ? `in ${p.days_until_earnings}d`
                : `${Math.abs(p.days_until_earnings)}d ago`}
          </li>
        )}
        {typeof p.days_until_exdiv === "number" && (
          <li>
            Ex-div:{" "}
            <span className="font-mono">{p.next_exdiv_date}</span>
            {typeof p.next_dividend_amount === "number" && (
              <>
                {" "}
                · <span className="font-mono">${p.next_dividend_amount.toFixed(2)}</span>
              </>
            )}{" "}
            ·{" "}
            {p.days_until_exdiv === 0
              ? "today"
              : p.days_until_exdiv > 0
                ? `in ${p.days_until_exdiv}d`
                : `${Math.abs(p.days_until_exdiv)}d ago`}
          </li>
        )}
      </ul>
    </div>
  );
}
