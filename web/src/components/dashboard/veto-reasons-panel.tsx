import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

type VetoRow = {
  payload: { ticker?: string; tcs?: number; reason?: string };
  created_at: string;
};

type Bucket = {
  key: string;
  label: string;
  hint: string;
  count: number;
  examples: { ticker: string; reason: string; tcs?: number }[];
  // Which Bot Tuning lever (if any) lets the user relax this filter.
  lever?: string;
};

/**
 * Risk Manager veto-reasons panel.
 *
 * 21 signals fired and 0 trades makes the chain feel broken — but the
 * truth is usually that Risk Manager vetoed every signal for a specific
 * reason. This panel groups today's vetoes by reason class
 * (Liquidity / Spread / Direction / Overextension / Capital / Kill
 * switch / Filter / Market), counts them, and quotes a worked example
 * with the actual reason string from the agent so the user can see
 * which filter to relax — or whether the filters are doing their job
 * and there just isn't a clean setup yet today.
 */
export async function VetoReasonsPanel({ userId }: { userId: string }) {
  const supabase = createClient();
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);

  const fetchRows = async (filterByUser: boolean) => {
    let q = supabase
      .from("agent_messages")
      .select("payload, created_at")
      .eq("agent_name", "risk_manager")
      .eq("kind", "veto")
      .gte("created_at", todayStart.toISOString())
      .order("created_at", { ascending: false })
      .limit(200);
    if (filterByUser) q = q.eq("user_id", userId);
    else q = q.is("user_id", null);
    const { data } = await q;
    return (data ?? []) as VetoRow[];
  };

  let rows = await fetchRows(true);
  if (rows.length === 0) rows = await fetchRows(false);

  if (rows.length === 0) {
    return (
      <section className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-5">
        <h2 className="font-serif text-xl text-weave-800">Risk Manager — clean</h2>
        <p className="text-sm text-weave-700 leading-relaxed">
          No vetoes today. Either nothing scored above the TCS threshold,
          or every signal that did was approved.
        </p>
      </section>
    );
  }

  // Classify each veto by reason. Order matters — first match wins.
  const PATTERNS: { key: string; label: string; hint: string; test: RegExp; lever?: string }[] = [
    {
      key: "killswitch",
      label: "Kill-switch",
      hint: "Daily loss / weekly drawdown / consecutive-loss cap was hit — new trades blocked for the rest of the day or until the streak breaks.",
      test: /kill.?switch|daily loss|weekly draw|consec/i,
      lever: "Bot Tuning · Losing-streak limit, Daily Loss Limit (Profile)."
    },
    {
      key: "direction",
      label: "Neutral / wrong-direction read",
      hint: "Trezo is long-only by default. A neutral or bearish signal is not an actionable trade.",
      test: /neutral direction|bearish|wrong.?direction|long.only|no actionable bias/i,
      lever: "Pattern Engine weights (Bot Tuning) or pick a different watchlist."
    },
    {
      key: "liquidity",
      label: "Liquidity (low average volume)",
      hint: "Symbol's average daily volume is below the liquidity floor (default 250k shares). Most thin market-wide small-caps still fail this.",
      test: /liquidity|average volume|avg volume|min.?volume/i,
      lever: "Liquidity floor: default 250k shares, tunable via TREZO_MIN_AVG_VOLUME in agents/.env (per-strategy lanes still apply)."
    },
    {
      key: "spread",
      label: "Bid/ask spread too wide",
      hint: "The current quote spread is wider than 0.5% — Risk Manager won't fire into illiquid books.",
      test: /spread|bid.?ask|illiquid|too wide/i,
      lever: "Bot Tuning · Max spread (when exposed; currently hardcoded 0.5%)."
    },
    {
      key: "overextension",
      label: "Overextended price",
      hint: "Price is >4 ATR from its 20-day mean. The bot won't chase parabolic moves.",
      test: /overextend|atr|stretched/i,
      lever: "Pattern Engine reweight — lower Trend factor."
    },
    {
      key: "market_filter",
      label: "Market filter (SPY/QQQ direction)",
      hint: "Broad market is moving against the signal's direction — longs blocked in a bearish tape, shorts in a bullish one.",
      test: /broad.?market|spy.?qqq|market filter|against.market|session vwap|broad tape/i,
      lever: "Wait for the tape — or relax in Adaptive Scope autonomy."
    },
    {
      key: "capital",
      label: "Capital / budget gate",
      hint: "Market-type budget under the active posture (Auto / Growth / Balanced / Income) is used up.",
      test: /budget|capital|posture|notional/i,
      lever: "Bot Tuning · Account Posture or per-market-type overrides."
    },
    {
      key: "tcs",
      label: "TCS below threshold",
      hint: "Signal score didn't clear the Signal TCS threshold in Bot Tuning.",
      test: /tcs|threshold|below.{0,5}(700|750|650)/i,
      lever: "Bot Tuning · Signal TCS threshold."
    },
    {
      key: "scope",
      label: "Adaptive Scope ticker flag",
      hint: "An event (earnings, halt, breaking news) flagged this ticker — Risk Manager honors the flag until TTL.",
      test: /scope|ticker.{0,5}flag|event flag/i,
      lever: "Strategy Engine · review Scope adjustments."
    }
  ];

  const buckets: Map<string, Bucket> = new Map();
  for (const row of rows) {
    const reason = String(row.payload?.reason ?? "").trim() || "(no reason)";
    const ticker = String(row.payload?.ticker ?? "?");
    const tcs = row.payload?.tcs;
    const p = PATTERNS.find((pp) => pp.test.test(reason));
    const k = p?.key ?? "other";
    const b = buckets.get(k) ?? {
      key: k,
      label: p?.label ?? "Other",
      hint: p?.hint ?? "Other reasons — see examples below.",
      count: 0,
      examples: [],
      lever: p?.lever
    };
    b.count += 1;
    if (b.examples.length < 3) b.examples.push({ ticker, reason, tcs });
    buckets.set(k, b);
  }
  const ordered = Array.from(buckets.values()).sort((a, b) => b.count - a.count);
  const total = rows.length;

  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50/40 p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Why Risk Manager vetoed today
          </h2>
          <p className="beginner-only text-xs text-weave-600 leading-relaxed mt-1">
            Signals fired, but Risk Manager rejected them. This panel
            groups vetoes by reason so you can see exactly which filter
            to relax — or whether the filters are doing their job and
            there is simply no clean setup yet today.
          </p>
        </div>
        <span className="text-[11px] uppercase tracking-widest text-amber-900">
          {total} veto{total === 1 ? "" : "es"} today
        </span>
      </div>
      <div className="space-y-2">
        {ordered.map((b) => (
          <div
            key={b.key}
            className={cn(
              "rounded-lg border bg-white p-3 space-y-1.5",
              b.count >= total * 0.5 ? "border-amber-300" : "border-weave-100"
            )}
          >
            <div className="flex items-baseline justify-between gap-2 flex-wrap">
              <p className="font-medium text-weave-800 text-sm">{b.label}</p>
              <span className="text-[11px] font-mono text-weave-600">
                {b.count} / {total}
              </span>
            </div>
            <p className="text-xs text-weave-600 leading-relaxed">{b.hint}</p>
            {b.lever && (
              <p className="text-xs text-emerald-800">
                <span className="font-medium">Where to adjust:</span> {b.lever}
              </p>
            )}
            <div className="text-[11px] text-weave-500 space-y-0.5 pt-1">
              {b.examples.map((ex, i) => (
                <p key={i} className="font-mono">
                  <span className="font-medium text-weave-700">{ex.ticker}</span>
                  {ex.tcs !== undefined ? ` · TCS ${ex.tcs}` : ""} — {ex.reason}
                </p>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
