/**
 * Server-only helper: was the option premium Trezo sold expensive or cheap?
 *
 * Natenberg's point is that selling options IS selling volatility, and the
 * seller's edge is the gap between the volatility priced INTO the option and
 * the volatility the underlying actually delivers. Trezo measured that gap
 * nowhere until 2026-08-05.
 *
 * These verdicts gate nothing. They exist so that, once enough of them have
 * accumulated, we can check whether CHEAP trades really did do worse than
 * RICH ones before any rule is changed on the strength of a theory.
 *
 * Returns null on miss / timeout, never throws.
 */

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export type PremiumVerdict = "RICH" | "FAIR" | "CHEAP" | "UNKNOWN";

export type PremiumRow = {
  ts: string;
  ticker: string;
  verdict: PremiumVerdict;
  impliedVol: number | null;
  realizedVol: number | null;
  why: string;
};

export type PremiumQuality = {
  total: number;
  counts: Record<string, number>;
  recent: PremiumRow[];
};

function verdictOf(v: unknown): PremiumVerdict {
  return v === "RICH" || v === "FAIR" || v === "CHEAP" ? v : "UNKNOWN";
}

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export async function fetchPremiumQuality(
  days = 14,
): Promise<PremiumQuality | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/options/premium_quality?days=${days}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(6000),
    });
    if (!r.ok) return null;
    const j: unknown = await r.json();
    if (!j || typeof j !== "object") return null;
    const body = j as Record<string, unknown>;
    const raw = Array.isArray(body.recent) ? body.recent : [];
    return {
      total: num(body.total) ?? 0,
      counts: (body.counts as Record<string, number>) ?? {},
      recent: raw.map((x) => {
        const o = (x ?? {}) as Record<string, unknown>;
        return {
          ts: String(o.ts ?? ""),
          ticker: String(o.ticker ?? ""),
          verdict: verdictOf(o.verdict),
          impliedVol: num(o.implied_vol),
          realizedVol: num(o.realized_vol),
          why: String(o.why ?? ""),
        };
      }),
    };
  } catch {
    return null;
  }
}
