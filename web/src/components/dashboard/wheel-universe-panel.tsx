const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type Candidate = {
  ticker: string;
  source: "seed" | "watchlist" | "position" | "market_wide" | string;
  yield_pct: number;
};

type UniverseResponse = {
  ok: boolean;
  count: number;
  candidates: Candidate[];
};

const SOURCE_LABEL: Record<string, string> = {
  seed: "Seed",
  watchlist: "Watchlist",
  position: "Held",
  market_wide: "Market",
};

const SOURCE_TONE: Record<string, string> = {
  seed: "bg-weave-100 text-weave-700",
  watchlist: "bg-treasure-100 text-treasure-800",
  position: "bg-emerald-100 text-emerald-800",
  market_wide: "bg-sky-100 text-sky-800",
};

/**
 * WheelUniversePanel - shows today's per-user wheel universe with
 * reason chips. Mike 2026-06-01: the wheel is no longer restricted
 * to a static 17-name list. Anything in a dividend-tagged watchlist
 * with a known yield >= 1.5% joins the universe, plus any name with
 * an active option position stays in. This panel makes the dynamic
 * composition visible.
 */
export async function WheelUniversePanel({ userId }: { userId: string }) {
  let data: UniverseResponse | null = null;
  try {
    const r = await fetch(
      `${AGENTS_BASE}/wheel/universe?user_id=${encodeURIComponent(userId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(6000) }
    );
    if (r.ok) data = (await r.json()) as UniverseResponse;
  } catch {
    data = null;
  }
  if (!data || data.count === 0) return null;

  // Group by source for the count badges.
  const counts = data.candidates.reduce<Record<string, number>>((acc, c) => {
    acc[c.source] = (acc[c.source] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-medium text-weave-800">
            Wheel universe today
          </h2>
          <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
            Every name the Wheel is allowed to consider this tick.
            Seed = curated baseline. Watchlist = added via your
            dividend-tagged watchlists. Held = active option position
            the bot keeps cycling. Market = cross-sector liquid
            dividend payers (the bot is not locked to your watchlist).
            Quality gate (yield ≥ 1.5%) applies to all additions.
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest">
          {Object.entries(counts).map(([src, n]) => (
            <span
              key={src}
              className={`rounded-full px-2 py-0.5 ${
                SOURCE_TONE[src] ?? "bg-weave-100 text-weave-700"
              }`}
            >
              {SOURCE_LABEL[src] ?? src} · {n}
            </span>
          ))}
        </div>
      </div>

      <ul className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-7 gap-1.5">
        {data.candidates.map((c) => (
          <li
            key={c.ticker}
            className={`rounded border border-weave-100 px-2 py-1.5 text-xs flex items-baseline justify-between gap-1 ${
              c.source === "position"
                ? "bg-emerald-50/50"
                : c.source === "watchlist"
                ? "bg-treasure-50/40"
                : c.source === "market_wide"
                ? "bg-sky-50/40"
                : "bg-weave-50/30"
            }`}
          >
            <span className="font-mono font-medium text-weave-800">
              {c.ticker}
            </span>
            <span className="text-[10px] text-weave-500">
              {(c.yield_pct * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
