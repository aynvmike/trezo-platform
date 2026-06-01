/**
 * Finnhub service wrapper.
 * Free tier: 60 requests/minute. We enforce a soft rate-limit in addition
 * to caching to avoid burning the quota.
 *
 * Cache TTLs:
 *  - quote:    30s
 *  - profile:  24h
 *  - news:     5m
 */

import { cacheGetOrSet } from "@/lib/cache";

export type StockQuote = {
  symbol: string;
  current: number;
  change: number;        // absolute dollar change
  changePercent: number; // %
  high: number;
  low: number;
  open: number;
  previousClose: number;
  timestamp: number;     // unix seconds
};

export type CompanyProfile = {
  symbol: string;
  name: string;
  exchange: string;
  industry: string;
  marketCap: number;     // in $M
  logo: string;
  weburl: string;
  ipo: string;           // YYYY-MM-DD
};

export type NewsItem = {
  id: number;
  headline: string;
  summary: string;
  source: string;
  url: string;
  publishedAt: number;
};

// --- internal -----------------------------------------------------------

const BASE = "https://finnhub.io/api/v1";

function key(): string {
  const k = process.env.FINNHUB_API_KEY;
  if (!k) throw new Error("FINNHUB_API_KEY not set");
  return k;
}

async function fh<T>(path: string, params: Record<string, string>): Promise<T> {
  const q = new URLSearchParams({ ...params, token: key() }).toString();
  const r = await fetch(`${BASE}${path}?${q}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal: AbortSignal.timeout(8000)
  });
  if (r.status === 429) {
    throw new Error("Finnhub rate limit hit — slow down or upgrade plan");
  }
  if (!r.ok) {
    throw new Error(`Finnhub ${r.status}: ${r.statusText}`);
  }
  return (await r.json()) as T;
}

// --- public API ---------------------------------------------------------

/**
 * Single-ticker quote. Cached 30s.
 */
export async function getQuote(symbol: string): Promise<StockQuote> {
  const sym = symbol.toUpperCase();
  return cacheGetOrSet<StockQuote>(`finnhub:quote:${sym}`, 30, async () => {
    type Raw = { c: number; d: number; dp: number; h: number; l: number; o: number; pc: number; t: number };
    const d = await fh<Raw>("/quote", { symbol: sym });
    return {
      symbol: sym,
      current: d.c ?? 0,
      change: d.d ?? 0,
      changePercent: d.dp ?? 0,
      high: d.h ?? 0,
      low: d.l ?? 0,
      open: d.o ?? 0,
      previousClose: d.pc ?? 0,
      timestamp: d.t ?? 0
    };
  });
}

/**
 * Multi-ticker quotes (sequential to respect free-tier rate limits).
 * Returns whatever it could fetch — silently drops failures.
 */
export async function getQuotes(symbols: string[]): Promise<StockQuote[]> {
  const out: StockQuote[] = [];
  for (const s of symbols) {
    try {
      out.push(await getQuote(s));
    } catch {
      // skip on error so one bad ticker doesn't ruin the whole batch
    }
  }
  return out;
}

/**
 * Company profile (sector, market cap, logo, etc.). Cached 24h.
 */
export async function getProfile(symbol: string): Promise<CompanyProfile | null> {
  const sym = symbol.toUpperCase();
  return cacheGetOrSet<CompanyProfile | null>(
    `finnhub:profile:${sym}`,
    60 * 60 * 24,
    async () => {
      type Raw = {
        name?: string;
        exchange?: string;
        finnhubIndustry?: string;
        marketCapitalization?: number;
        logo?: string;
        weburl?: string;
        ipo?: string;
      };
      const d = await fh<Raw>("/stock/profile2", { symbol: sym });
      if (!d || !d.name) return null;
      return {
        symbol: sym,
        name: d.name,
        exchange: d.exchange ?? "",
        industry: d.finnhubIndustry ?? "",
        marketCap: d.marketCapitalization ?? 0,
        logo: d.logo ?? "",
        weburl: d.weburl ?? "",
        ipo: d.ipo ?? ""
      };
    }
  );
}

/**
 * Company news for the last N days (default 7). Cached 5m.
 */
export async function getNews(symbol: string, days = 7): Promise<NewsItem[]> {
  const sym = symbol.toUpperCase();
  return cacheGetOrSet<NewsItem[]>(`finnhub:news:${sym}:${days}`, 300, async () => {
    const to = new Date();
    const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    type Raw = {
      id: number;
      headline: string;
      summary: string;
      source: string;
      url: string;
      datetime: number;
    }[];
    const items = await fh<Raw>("/company-news", {
      symbol: sym,
      from: fmt(from),
      to: fmt(to)
    });
    return items.slice(0, 10).map((n) => ({
      id: n.id,
      headline: n.headline,
      summary: n.summary,
      source: n.source,
      url: n.url,
      publishedAt: n.datetime
    }));
  });
}
