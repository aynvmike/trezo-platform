/**
 * Server-only helper for fetching the live Wheel positions snapshot
 * from the agents service. Used by both `WheelLivePositions` (the
 * dedicated card) and the Wheel page's top KPI tiles so they share a
 * single source of truth — premium-at-work, cash secured, and
 * unrealized P&L all reflect the real Alpaca account when connected.
 *
 * Returns null on miss / timeout / bad shape, never throws. Caller is
 * responsible for falling back to modeled data when this returns null
 * or `configured: false`.
 */

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export type WheelLiveOption = {
  occ: string;
  underlying: string;
  type: "call" | "put" | string;
  strike: number;
  expiration: string;
  contracts: number;
  side: string;
  leg: "wheel_csp" | "wheel_cc" | "long_option" | string;
  avg_entry_price: number;
  market_value: number;
  unrealized_pl: number;
  net_premium_usd: number;
};

export type WheelLiveEquity = {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  market_value: number;
  unrealized_pl: number;
};

export type WheelLiveSnapshot = {
  configured: boolean;
  routed?: string;
  options?: WheelLiveOption[];
  equity?: WheelLiveEquity[];
  as_of?: string;
  note?: string;
};

export async function fetchWheelLiveSnapshot(
  userId: string
): Promise<WheelLiveSnapshot | null> {
  const qs = new URLSearchParams({ user_id: userId }).toString();
  try {
    const r = await fetch(`${AGENTS_BASE}/wheel/positions?${qs}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) return null;
    return (await r.json()) as WheelLiveSnapshot;
  } catch {
    return null;
  }
}

/**
 * Derive the headline numbers from a live snapshot. Returns null when
 * the snapshot isn't configured or has no options data — caller
 * falls through to modeled totals in that case.
 */
export function summariseLiveWheel(snap: WheelLiveSnapshot | null): {
  open_csps: number;
  open_ccs: number;
  premium_at_work_usd: number;
  cash_secured_usd: number;
  unrealized_pl_usd: number;
} | null {
  if (!snap?.configured) return null;
  const options = snap.options ?? [];
  if (options.length === 0) return null;

  const csps = options.filter((o) => o.leg === "wheel_csp");
  const ccs = options.filter((o) => o.leg === "wheel_cc");

  // Premium at work = sum of net credit collected on every open leg.
  // The agents endpoint sets net_premium_usd to (avg_entry_price * 100 *
  // contracts) with the sign matching whether we're short or long the
  // contract, so summing here is correct.
  const premium = options.reduce(
    (a, o) => a + (Number(o.net_premium_usd) || 0),
    0
  );

  // Cash secured = strike * 100 * contracts on every open CSP.
  // This is the buying-power the broker is reserving against assignment.
  const cashSecured = csps.reduce(
    (a, o) => a + Number(o.strike) * 100 * Number(o.contracts),
    0
  );

  const unrealized = options.reduce(
    (a, o) => a + (Number(o.unrealized_pl) || 0),
    0
  );

  return {
    open_csps: csps.length,
    open_ccs: ccs.length,
    premium_at_work_usd: premium,
    cash_secured_usd: cashSecured,
    unrealized_pl_usd: unrealized,
  };
}
