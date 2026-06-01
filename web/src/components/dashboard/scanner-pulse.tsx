import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

/**
 * Scanner Pulse — server widget that surfaces the most recent
 * pattern_detection scan summary. Used on the Paper Trading page so
 * the user can see why trades may not be firing without hunting in
 * the activity feed: "Scanned 14 tickers at TCS 700; strongest read
 * was AMD at 612 (bullish) — below threshold, nothing fired."
 *
 * Also surfaces per-ticker Strategy Engine switches this tick — when
 * the per-stock chosen strategy flips (e.g. pattern → orb), each
 * change is rendered as a chip so the user can see the engine
 * adapting in real time rather than digging in the activity feed.
 */

type Change = {
  ticker: string;
  from: string;
  to: string;
  tcs?: number;
  direction?: string;
};

type Row = {
  payload: {
    note?: string;
    tickers_scanned?: number;
    signals?: number;
    max_tcs?: number;
    max_tcs_ticker?: string | null;
    max_tcs_direction?: string;
    threshold?: number;
    bullish_count?: number;
    from_watchlist?: number;
    from_market_wide?: number;
    strategy_changes?: Change[];
    strategy_change_count?: number;
  };
  created_at: string;
};

export async function ScannerPulse({ userId }: { userId: string }) {
  const supabase = createClient();

  // Pull the most recent pattern_detection info row for this user — and
  // a fallback global row, in case ticks fired before per-user wiring.
  const { data: userRow } = await supabase
    .from("agent_messages")
    .select("payload, created_at")
    .eq("agent_name", "pattern_detection")
    .eq("kind", "info")
    .eq("user_id", userId)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  let row = userRow as Row | null;
  if (!row) {
    const { data: globalRow } = await supabase
      .from("agent_messages")
      .select("payload, created_at")
      .eq("agent_name", "pattern_detection")
      .eq("kind", "info")
      .is("user_id", null)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    row = globalRow as Row | null;
  }

  if (!row) {
    return (
      <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-500">
        <p className="font-medium text-weave-700">Scanner pulse — no data yet</p>
        <p className="mt-1 leading-relaxed">
          The Pattern Detection agent has not posted a scan summary yet.
          That usually means the agents service is not running. Start it
          (the FastAPI service on port 8001) and reload — the first
          summary appears within 60 seconds.
        </p>
      </div>
    );
  }

  const p = row.payload;
  const fired = (p.signals ?? 0) > 0;
  const max = p.max_tcs ?? 0;
  const threshold = p.threshold ?? 700;
  const suggested = Math.max(300, Math.min(threshold, Math.max(max, 0) + 20));
  const showSuggest = !fired && max > 0 && suggested < threshold;
  const changes = Array.isArray(p.strategy_changes) ? p.strategy_changes : [];
  const changeCount = p.strategy_change_count ?? changes.length;

  const ago = relativeTime(row.created_at);

  return (
    <div
      className={cn(
        "rounded-xl border p-5 space-y-2",
        fired
          ? "border-emerald-200 bg-emerald-50"
          : "border-amber-200 bg-amber-50"
      )}
    >
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <p className="font-medium text-weave-800">Scanner pulse · last tick {ago}</p>
        <span className="text-[11px] uppercase tracking-widest text-weave-500">
          {p.tickers_scanned ?? 0} scanned
          {typeof p.from_watchlist === "number" && typeof p.from_market_wide === "number" && (p.from_watchlist + p.from_market_wide) > 0
            ? ` (${p.from_watchlist} watchlist + ${p.from_market_wide} market-wide)`
            : ""}
          {" · threshold "}{threshold}
        </span>
      </div>
      <p className="text-sm text-weave-700 leading-relaxed">
        {p.note || "No summary in payload."}
      </p>
      {changeCount > 0 && (
        <div className="rounded-lg border border-weave-200 bg-white/70 p-3 space-y-2">
          <p className="text-xs font-medium text-weave-700">
            Strategy Engine — {changeCount} pick(s) flipped this tick
          </p>
          <p className="beginner-only text-[11px] text-weave-500 leading-relaxed">
            Trezo retests each stock under every eligible strategy every
            minute. When the best-performing read shifts, the strategy
            for that stock flips with it — these chips show today&apos;s
            switches so you can watch the engine adapt.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {changes.map((c, i) => (
              <span
                key={`${c.ticker}-${i}`}
                className="inline-flex items-center gap-1 rounded-full bg-treasure-100 px-2 py-0.5 text-[11px] text-weave-700"
                title={
                  c.tcs
                    ? `${c.ticker}: ${c.from} → ${c.to} · TCS ${c.tcs} (${c.direction ?? "n/a"})`
                    : `${c.ticker}: ${c.from} → ${c.to}`
                }
              >
                <span className="font-mono font-medium">{c.ticker}</span>
                <span className="text-weave-500">{c.from}</span>
                <span className="text-weave-400">→</span>
                <span className="font-medium text-weave-700">{c.to}</span>
              </span>
            ))}
            {changeCount > changes.length && (
              <span className="text-[11px] text-weave-500">
                +{changeCount - changes.length} more
              </span>
            )}
          </div>
        </div>
      )}
      {!fired && p.max_tcs_direction === "bearish" && (
        <p className="text-xs text-amber-800">
          The strongest read was <span className="font-medium">bearish</span> —
          Trezo is long-only by default, so a bearish read does not become a
          trade. Lowering TCS alone will not change this; the watchlist needs
          a bullish read above threshold (or you switch to a different
          watchlist for the window).
        </p>
      )}
      {!fired && showSuggest && p.max_tcs_direction !== "bearish" && (
        <p className="text-xs text-weave-600">
          Try lowering Signal TCS in Bot Tuning to{" "}
          <span className="font-mono font-medium">{suggested}</span> — that
          would have fired on the strongest read this tick.
        </p>
      )}
      {!fired && max === 0 && (
        <p className="text-xs text-weave-600">
          The scanner saw nothing scoreable — either your watchlist is empty
          or the data feeds have not caught up yet.
        </p>
      )}
    </div>
  );
}

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return iso;
  const diff = Date.now() - t;
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleString();
}
