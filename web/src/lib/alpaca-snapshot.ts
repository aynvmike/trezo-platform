/**
 * Server-only helper for fetching the Alpaca paper-account snapshot.
 * One source for the Paper Trading page's KPI override AND the
 * AlpacaSnapshot details panel — Next.js dedupes the fetch within a
 * single request so it only hits the agents service once.
 */

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

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
};

export async function fetchAlpacaSnapshot(): Promise<AlpacaSnapshot | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/paper/alpaca-snapshot`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    if (!r.ok) return null;
    return (await r.json()) as AlpacaSnapshot;
  } catch {
    return null;
  }
}
