/**
 * Server-only helper for fetching the Alpaca paper-account snapshot.
 * One source for the Paper Trading page's KPI override AND the
 * AlpacaSnapshot details panel — Next.js dedupes the fetch within a
 * single request so it only hits the agents service once.
 */

import { cacheGet, cacheSet } from "@/lib/cache";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";
const SNAP_CACHE_KEY = "alpaca:last-snapshot";
const SNAP_TTL_SEC = 24 * 60 * 60;

export type AlpacaAccount = {
  equity: number;
  last_equity: number;
  cash: number;
  buying_power: number;
  currency: string;
  status: string;
  pattern_day_trader: boolean;
  daytrade_count: number;
  trading_blocked: boolean;
  // Options approval level reported by Alpaca. 0 = not approved,
  // 1 = covered (CSP + CC), 2 = long + spreads, 3 = uncovered.
  // Returned by the agents `/paper/alpaca-snapshot` endpoint via the
  // dataclass in `agents/app/brokers/alpaca.py`. Surfaced by the
  // `OptionsApprovalBadge` server component on Live Trading settings
  // and the Wheel page.
  options_approved_level?: number;
  options_trading_level?: number;
};

export type AlpacaPosition = {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  market_value: number;
  current_price: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  side: string;
};

export type AlpacaSnapshot = {
  configured: boolean;
  venue?: string;
  account?: AlpacaAccount;
  positions?: AlpacaPosition[];
  as_of?: string;
  note?: string;
  // Set when this snapshot is the last-known cached copy served because the
  // live agents service was unreachable; cached_at is when it was captured.
  stale?: boolean;
  cached_at?: string;
};

export async function fetchAlpacaSnapshot(): Promise<AlpacaSnapshot | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/paper/alpaca-snapshot`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    if (!r.ok) throw new Error(`status ${r.status}`);
    const snap = (await r.json()) as AlpacaSnapshot;
    // Remember the last live snapshot that carried real account data, so the
    // dashboard can show "last known" numbers when 8001 is later unreachable.
    if (snap?.configured && snap?.account) {
      await cacheSet(
        SNAP_CACHE_KEY,
        { ...snap, stale: false, cached_at: new Date().toISOString() },
        SNAP_TTL_SEC
      );
    }
    return { ...snap, stale: false };
  } catch {
    // Service unreachable -> serve the last known good snapshot (marked stale)
    // so the platform shows last-known data instead of blanks.
    const last = await cacheGet<AlpacaSnapshot>(SNAP_CACHE_KEY);
    if (last?.account) return { ...last, stale: true };
    return null;
  }
}

// --- Agent per-position advice (Mike 2026-07-28) ---------------------
// "I would like to start looking into getting the agents recommendations
// in as well on what to change on certain trades or options."
export type PositionAdvice = {
  ticker: string;
  lane: string;
  verdict: "BANK" | "TIGHTEN" | "CUT" | "TRIM" | "WATCH" | "HOLD";
  why: string;
  action: string;
  days_held: number;
  at_broker: boolean | null;
  unrealized_usd?: number;
  unrealized_pct?: number;
  giveback_pct?: number;
  to_target_pct?: number | null;
  stop_room_pct?: number | null;
};

export async function fetchPositionAdvice(): Promise<Record<string, PositionAdvice>> {
  // Keyed by TICKER so the position cards can look theirs up directly.
  // Fail-quiet: no advice simply means the cards render as before.
  try {
    const r = await fetch(`${AGENTS_BASE}/knowledge/advice`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) return {};
    const j = (await r.json()) as { positions?: PositionAdvice[] };
    const out: Record<string, PositionAdvice> = {};
    for (const p of j.positions ?? []) {
      const k = String(p.ticker).toUpperCase();
      // Keep the most urgent verdict when a name has several rows
      // (crypto accumulation opens one row per add).
      const rank = { BANK: 0, TIGHTEN: 1, CUT: 2, TRIM: 3, WATCH: 4, HOLD: 5 };
      if (!out[k] || rank[p.verdict] < rank[out[k].verdict]) out[k] = p;
    }
    return out;
  } catch {
    return {};
  }
}
