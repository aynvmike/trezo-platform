/**
 * CoinGecko service wrapper.
 * Public endpoint — no API key required.
 * Cache TTL: 30 seconds (Phase 2 spec).
 */

import { cacheGetOrSet } from "@/lib/cache";

export type CryptoPrice = {
  id: string;          // CoinGecko id, e.g. "ripple"
  symbol: string;      // e.g. "XRP"
  name: string;        // human-readable, e.g. "XRP"
  priceUsd: number;
  change24h: number;   // percent, e.g. -2.34
  marketCap: number;
  lastUpdated: string; // ISO timestamp
};

const COIN_MAP: Record<string, { id: string; symbol: string; name: string }> = {
  XRP: { id: "ripple",   symbol: "XRP", name: "XRP" },
  ETH: { id: "ethereum", symbol: "ETH", name: "Ethereum" },
  SOL: { id: "solana",   symbol: "SOL", name: "Solana" },
  BTC: { id: "bitcoin",  symbol: "BTC", name: "Bitcoin" }
};

const DEFAULT_SYMBOLS = ["XRP", "ETH", "SOL"];

/**
 * Fetch live prices for the given symbols (default: XRP/ETH/SOL).
 * Cached for 30 seconds.
 */
export async function getCryptoPrices(
  symbols: string[] = DEFAULT_SYMBOLS
): Promise<CryptoPrice[]> {
  const normalized = symbols.map((s) => s.toUpperCase()).filter((s) => COIN_MAP[s]);
  const ids = normalized.map((s) => COIN_MAP[s].id).join(",");
  if (!ids) return [];

  const cacheKey = `coingecko:prices:${normalized.sort().join(",")}`;

  return cacheGetOrSet<CryptoPrice[]>(cacheKey, 30, async () => {
    const url =
      `https://api.coingecko.com/api/v3/simple/price` +
      `?ids=${ids}` +
      `&vs_currencies=usd` +
      `&include_24hr_change=true` +
      `&include_market_cap=true` +
      `&include_last_updated_at=true`;

    const r = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      // CoinGecko sometimes rate-limits; 8s timeout is plenty
      signal: AbortSignal.timeout(8000)
    });

    if (!r.ok) {
      throw new Error(`CoinGecko ${r.status}: ${r.statusText}`);
    }

    const data = (await r.json()) as Record<
      string,
      {
        usd: number;
        usd_24h_change?: number;
        usd_market_cap?: number;
        last_updated_at?: number;
      }
    >;

    return normalized.map((sym) => {
      const meta = COIN_MAP[sym];
      const d = data[meta.id] ?? { usd: 0 };
      return {
        id: meta.id,
        symbol: meta.symbol,
        name: meta.name,
        priceUsd: d.usd ?? 0,
        change24h: d.usd_24h_change ?? 0,
        marketCap: d.usd_market_cap ?? 0,
        lastUpdated: d.last_updated_at
          ? new Date(d.last_updated_at * 1000).toISOString()
          : new Date().toISOString()
      };
    });
  });
}
