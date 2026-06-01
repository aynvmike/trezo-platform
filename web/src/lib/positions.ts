/**
 * Server helpers for the Dividends layer's holdings (user_positions).
 *
 * The layer tracks what the user ACTUALLY holds — no placeholder
 * seeding. A new user starts empty and adds their own holdings, from
 * any family in the income-ETF library or as a custom ticker.
 *
 * The library is curated, not exhaustive — it covers the families a
 * real income investor reaches for: YieldMax single-stock covered
 * calls, REX / NEOS / Roundhill premium income, JPMorgan premium
 * income, Global X covered-call indices, iShares dividend, Schwab /
 * Vanguard dividend growth, high-yield bond, REIT / MLP / preferred.
 */

import { createClient } from "@/lib/supabase/server";

export type PositionRow = {
  id: string;
  ticker: string;
  asset_type: string;
  shares: number;
  avg_cost: number | null;
  cumulative_dist: number;
  notes: string | null;
  drip_enabled: boolean;
  dist_yield_pct: number;
};

export type IncomeEtfFamily =
  | "YieldMax"
  | "REX / NEOS / Roundhill"
  | "JPMorgan premium income"
  | "Global X covered call"
  | "iShares dividend"
  | "Schwab / Vanguard dividend growth"
  | "High-yield bond"
  | "REIT, MLP & preferred";

export type IncomeEtf = {
  ticker: string;
  name: string;
  family: IncomeEtfFamily;
  /** Typical trailing distribution yield, used as the default when a
   *  user adds the ETF. They can edit it on the holding card. */
  dist_yield_pct: number;
};

/**
 * Curated income-ETF library across every major family. Yields are
 * round-number estimates of trailing distribution rates — useful as
 * defaults; edit on the holding card.
 */
export const INCOME_ETF_LIBRARY: IncomeEtf[] = [
  // ---------- YieldMax (single-stock covered calls) ----------
  { ticker: "TSLY", name: "Tesla option income", family: "YieldMax", dist_yield_pct: 60 },
  { ticker: "NVDY", name: "Nvidia option income", family: "YieldMax", dist_yield_pct: 55 },
  { ticker: "CONY", name: "Coinbase option income", family: "YieldMax", dist_yield_pct: 70 },
  { ticker: "MSTY", name: "MicroStrategy option income", family: "YieldMax", dist_yield_pct: 95 },
  { ticker: "AMZY", name: "Amazon option income", family: "YieldMax", dist_yield_pct: 35 },
  { ticker: "GOOY", name: "Alphabet option income", family: "YieldMax", dist_yield_pct: 30 },
  { ticker: "APLY", name: "Apple option income", family: "YieldMax", dist_yield_pct: 25 },
  { ticker: "MSFO", name: "Microsoft option income", family: "YieldMax", dist_yield_pct: 25 },
  { ticker: "FBY", name: "Meta option income", family: "YieldMax", dist_yield_pct: 30 },
  { ticker: "NFLY", name: "Netflix option income", family: "YieldMax", dist_yield_pct: 40 },
  { ticker: "AMDY", name: "AMD option income", family: "YieldMax", dist_yield_pct: 50 },
  { ticker: "DISO", name: "Disney option income", family: "YieldMax", dist_yield_pct: 35 },
  { ticker: "JPMO", name: "JPMorgan option income", family: "YieldMax", dist_yield_pct: 18 },
  { ticker: "AIYY", name: "C3.ai option income", family: "YieldMax", dist_yield_pct: 60 },
  { ticker: "MRNY", name: "Moderna option income", family: "YieldMax", dist_yield_pct: 80 },
  { ticker: "SMCY", name: "Super Micro option income", family: "YieldMax", dist_yield_pct: 80 },
  { ticker: "PYPY", name: "PayPal option income", family: "YieldMax", dist_yield_pct: 50 },
  { ticker: "ABNY", name: "Airbnb option income", family: "YieldMax", dist_yield_pct: 40 },
  { ticker: "BABO", name: "Alibaba option income", family: "YieldMax", dist_yield_pct: 35 },
  { ticker: "SNOY", name: "Snowflake option income", family: "YieldMax", dist_yield_pct: 50 },
  { ticker: "GDXY", name: "Gold Miners option income", family: "YieldMax", dist_yield_pct: 40 },
  { ticker: "ULTY", name: "YieldMax Ultra income (rotating)", family: "YieldMax", dist_yield_pct: 65 },
  { ticker: "YMAX", name: "YieldMax Universe — fund of funds", family: "YieldMax", dist_yield_pct: 55 },
  { ticker: "YMAG", name: "YieldMax Magnificent 7 — fund of funds", family: "YieldMax", dist_yield_pct: 40 },

  // ---------- REX / NEOS / Roundhill / Goldman premium income ----------
  { ticker: "FEPI", name: "REX FANG+ Income", family: "REX / NEOS / Roundhill", dist_yield_pct: 25 },
  { ticker: "AIPI", name: "REX AI Equity Premium Income", family: "REX / NEOS / Roundhill", dist_yield_pct: 30 },
  { ticker: "QQQI", name: "NEOS Nasdaq-100 High Income", family: "REX / NEOS / Roundhill", dist_yield_pct: 14 },
  { ticker: "SPYI", name: "NEOS S&P 500 High Income", family: "REX / NEOS / Roundhill", dist_yield_pct: 12 },
  { ticker: "GPIQ", name: "Goldman Nasdaq-100 Core Premium", family: "REX / NEOS / Roundhill", dist_yield_pct: 11 },
  { ticker: "GPIX", name: "Goldman S&P 500 Core Premium", family: "REX / NEOS / Roundhill", dist_yield_pct: 9 },

  // ---------- JPMorgan premium income ----------
  { ticker: "JEPI", name: "JPMorgan Equity Premium Income", family: "JPMorgan premium income", dist_yield_pct: 8 },
  { ticker: "JEPQ", name: "JPMorgan Nasdaq Equity Premium Income", family: "JPMorgan premium income", dist_yield_pct: 11 },
  { ticker: "JPIE", name: "JPMorgan Income ETF", family: "JPMorgan premium income", dist_yield_pct: 6 },

  // ---------- Global X covered-call indices ----------
  { ticker: "QYLD", name: "Nasdaq-100 Covered Call", family: "Global X covered call", dist_yield_pct: 12 },
  { ticker: "XYLD", name: "S&P 500 Covered Call", family: "Global X covered call", dist_yield_pct: 10 },
  { ticker: "RYLD", name: "Russell 2000 Covered Call", family: "Global X covered call", dist_yield_pct: 13 },
  { ticker: "DIVO", name: "Equity Premium Income (Amplify)", family: "Global X covered call", dist_yield_pct: 5 },

  // ---------- iShares dividend ----------
  { ticker: "HDV", name: "Core High Dividend", family: "iShares dividend", dist_yield_pct: 4 },
  { ticker: "DVY", name: "Select Dividend", family: "iShares dividend", dist_yield_pct: 4 },
  { ticker: "DGRO", name: "Core Dividend Growth", family: "iShares dividend", dist_yield_pct: 2.5 },
  { ticker: "IDV", name: "International Select Dividend", family: "iShares dividend", dist_yield_pct: 6 },

  // ---------- Schwab / Vanguard dividend growth ----------
  { ticker: "SCHD", name: "Schwab U.S. Dividend Equity", family: "Schwab / Vanguard dividend growth", dist_yield_pct: 3.5 },
  { ticker: "VYM", name: "Vanguard High Dividend Yield", family: "Schwab / Vanguard dividend growth", dist_yield_pct: 3 },
  { ticker: "VIG", name: "Vanguard Dividend Appreciation", family: "Schwab / Vanguard dividend growth", dist_yield_pct: 2 },
  { ticker: "VYMI", name: "Vanguard International High Dividend", family: "Schwab / Vanguard dividend growth", dist_yield_pct: 4.5 },

  // ---------- High-yield bond ----------
  { ticker: "HYG", name: "iBoxx High Yield Corporate", family: "High-yield bond", dist_yield_pct: 7 },
  { ticker: "JNK", name: "Bloomberg High Yield Bond", family: "High-yield bond", dist_yield_pct: 7 },
  { ticker: "TLT", name: "20+ Year Treasury Bond", family: "High-yield bond", dist_yield_pct: 4 },
  { ticker: "SHY", name: "1-3 Year Treasury Bond", family: "High-yield bond", dist_yield_pct: 4.5 },

  // ---------- REIT, MLP & preferred ----------
  { ticker: "VNQ", name: "Vanguard Real Estate", family: "REIT, MLP & preferred", dist_yield_pct: 4 },
  { ticker: "SCHH", name: "Schwab U.S. REIT", family: "REIT, MLP & preferred", dist_yield_pct: 4 },
  { ticker: "AMLP", name: "Alerian MLP", family: "REIT, MLP & preferred", dist_yield_pct: 7 },
  { ticker: "PFF", name: "U.S. Preferred & Income Securities", family: "REIT, MLP & preferred", dist_yield_pct: 6 },
  { ticker: "O", name: "Realty Income (monthly dividend stock)", family: "REIT, MLP & preferred", dist_yield_pct: 5.5 }
];

/**
 * Back-compat: the original YIELDMAX_LIBRARY shape (no family/yield).
 * Filtered to the YieldMax family. Other consumers (watchlists page)
 * keep working unchanged.
 */
export const YIELDMAX_LIBRARY: { ticker: string; name: string }[] =
  INCOME_ETF_LIBRARY
    .filter((e) => e.family === "YieldMax")
    .map(({ ticker, name }) => ({ ticker, name }));

/**
 * The user's dividend-layer holdings — exactly what they hold. Returns
 * [] for a new user (nothing is auto-seeded).
 */
export async function getYieldMaxPositions(userId: string): Promise<PositionRow[]> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("user_positions")
    .select(
      "id, ticker, asset_type, shares, avg_cost, cumulative_dist, notes, drip_enabled, dist_yield_pct"
    )
    .eq("user_id", userId)
    .eq("asset_type", "yieldmax")
    .order("ticker");

  if (error) return [];
  return (data ?? []) as PositionRow[];
}
