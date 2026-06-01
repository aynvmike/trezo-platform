/**
 * Server-side helpers for the watchlist domain.
 *
 * - On first call, `getOrSeedDefaultWatchlist` creates a "Core Winners"
 *   default list seeded from TREZO_FOUNDER_WATCHLIST.md.
 * - All other helpers wrap Supabase queries and return typed rows.
 *
 * Server-only module — uses cookies-based Supabase client.
 */

import { createClient as createServerSupabase } from "@/lib/supabase/server";

export type Watchlist = {
  id: string;
  name: string;
  is_default: boolean;
  created_at: string;
};

export type WatchlistItem = {
  id: string;
  ticker: string;
  asset_type: "stock" | "crypto" | "option";
  notes: string | null;
  starred: boolean;
  position: number;
  ethical_override: boolean;
  ethical_override_reason: string | null;
};

// Founder watchlist — sourced from TREZO_FOUNDER_WATCHLIST.md "Core Winners"
const FOUNDER_CORE_WINNERS: { ticker: string; notes: string }[] = [
  { ticker: "CZR",   notes: "Best options performer" },
  { ticker: "WMT",   notes: "Stable swing trades" },
  { ticker: "INTC",  notes: "ITM/near-money calls" },
  { ticker: "AMD",   notes: "Semiconductor conviction" },
  { ticker: "AMSC",  notes: "Momentum capture" },
  { ticker: "GM",    notes: "Conservative wins" },
  { ticker: "RBLX",  notes: "Gaming sector strength" },
  { ticker: "CSCO",  notes: "Reliable mid-cap" },
  { ticker: "MRK",   notes: "Healthcare stability" },
  { ticker: "PYPL",  notes: "Fintech swing" }
];

// Example watchlists every new user starts with — variety so the
// dropdowns everywhere (Backtest, Simulation Lab, Pattern Engine)
// have more than one list to pick from out of the box. Users can
// edit / delete / add their own.
type ExampleList = {
  name: string;
  items: { ticker: string; asset_type: "stock" | "crypto"; notes?: string }[];
};

const EXAMPLE_WATCHLISTS: ExampleList[] = [
  {
    name: "Dividend ETFs · Examples",
    items: [
      { ticker: "SCHD", asset_type: "stock", notes: "Schwab dividend equity" },
      { ticker: "JEPI", asset_type: "stock", notes: "JPMorgan equity premium income" },
      { ticker: "JEPQ", asset_type: "stock", notes: "JPMorgan Nasdaq premium income" },
      { ticker: "VYM",  asset_type: "stock", notes: "Vanguard high dividend" },
      { ticker: "FEPI", asset_type: "stock", notes: "REX FANG+ income" },
      { ticker: "NVDY", asset_type: "stock", notes: "YieldMax Nvidia option income" },
      { ticker: "QYLD", asset_type: "stock", notes: "Global X Nasdaq covered call" }
    ]
  },
  {
    name: "Mega-Cap Swing · Examples",
    items: [
      { ticker: "AAPL", asset_type: "stock", notes: "Apple" },
      { ticker: "MSFT", asset_type: "stock", notes: "Microsoft" },
      { ticker: "GOOGL", asset_type: "stock", notes: "Alphabet" },
      { ticker: "AMZN", asset_type: "stock", notes: "Amazon" },
      { ticker: "NVDA", asset_type: "stock", notes: "Nvidia" },
      { ticker: "META", asset_type: "stock", notes: "Meta" },
      { ticker: "TSLA", asset_type: "stock", notes: "Tesla" }
    ]
  },
  {
    // GENIUS Act watchlist - reframes the old "Crypto Core" around
    // the regulatory + payments rail shift (S.1582 / 119th Congress,
    // ISO 20022 / Fedwire / FedNow / SWIFT MX). Mike 2026-06-01:
    // "speaks better for the current progress of the economy than
    // just the traded tokens." The 8 ISO 20022-aligned coins from
    // app/data/iso20022_coins.py form the core of this list.
    name: "GENIUS Act · Crypto",
    items: [
      { ticker: "BTC",  asset_type: "crypto", notes: "Bitcoin - reserve" },
      { ticker: "ETH",  asset_type: "crypto", notes: "Ethereum - smart-contract layer" },
      { ticker: "SOL",  asset_type: "crypto", notes: "Solana - high-throughput layer-1" },
      { ticker: "XRP",  asset_type: "crypto", notes: "Ripple - cross-border settlement (ISO 20022)" },
      { ticker: "XLM",  asset_type: "crypto", notes: "Stellar - remittance + tokenised assets (ISO 20022)" },
      { ticker: "ALGO", asset_type: "crypto", notes: "Algorand - central-bank pilots (ISO 20022)" },
      { ticker: "HBAR", asset_type: "crypto", notes: "Hedera - enterprise DLT (ISO 20022)" },
      { ticker: "QNT",  asset_type: "crypto", notes: "Quant - banking ↔ DLT interop (ISO 20022)" },
      { ticker: "XDC",  asset_type: "crypto", notes: "XDC Network - trade finance + RWAs (ISO 20022)" },
      { ticker: "IOTA", asset_type: "crypto", notes: "IOTA - M2M settlement (ISO 20022)" },
      { ticker: "XYO",  asset_type: "crypto", notes: "XYO Network - geospatial proof-of-location (ISO 20022)" }
    ]
  },
  {
    // Crypto-adjacent equities - companies whose earnings, IV, and
    // price action are driven by crypto + payments-rail news. The
    // agents need these in the universe so when (say) BlackRock
    // files a new ETF or Coinbase announces a custody deal, the
    // signal is picked up by stock scanners too. Mike 2026-06-01.
    name: "Crypto-adjacent · Equities",
    items: [
      { ticker: "COIN", asset_type: "stock", notes: "Coinbase - exchange + custody" },
      { ticker: "CRCL", asset_type: "stock", notes: "Circle - USDC issuer" },
      { ticker: "HOOD", asset_type: "stock", notes: "Robinhood - retail crypto" },
      { ticker: "MSTR", asset_type: "stock", notes: "Strategy - largest corporate BTC holder" },
      { ticker: "BLK",  asset_type: "stock", notes: "BlackRock - BTC + ETH spot ETFs" },
      { ticker: "MSFT", asset_type: "stock", notes: "Microsoft - enterprise blockchain + AI infra" },
      { ticker: "NVDA", asset_type: "stock", notes: "Nvidia - AI + crypto mining infrastructure" },
      { ticker: "IBM",  asset_type: "stock", notes: "IBM - Hyperledger + enterprise DLT" },
      { ticker: "MA",   asset_type: "stock", notes: "Mastercard - crypto rails partner" },
      { ticker: "V",    asset_type: "stock", notes: "Visa - stablecoin settlement pilots" },
      { ticker: "PYPL", asset_type: "stock", notes: "PayPal - PYUSD stablecoin" },
      { ticker: "XYZ",  asset_type: "stock", notes: "Block - BTC + retail integration" },
      { ticker: "MARA", asset_type: "stock", notes: "Marathon Digital - BTC miner" },
      { ticker: "RIOT", asset_type: "stock", notes: "Riot Platforms - BTC miner" },
      { ticker: "CLSK", asset_type: "stock", notes: "CleanSpark - BTC miner" }
    ]
  }
];

/**
 * Seed the user's account with example watchlists alongside Core
 * Winners. Idempotent — only creates a list when one with the same
 * name doesn't already exist. Run alongside getOrSeedDefaultWatchlist.
 */
export async function seedExampleWatchlists(userId: string): Promise<void> {
  const supabase = createServerSupabase();

  const { data: existing } = await supabase
    .from("watchlists")
    .select("name")
    .eq("user_id", userId);
  const have = new Set((existing ?? []).map((r) => r.name));

  for (const ex of EXAMPLE_WATCHLISTS) {
    if (have.has(ex.name)) continue;
    const { data: inserted, error } = await supabase
      .from("watchlists")
      .insert({ user_id: userId, name: ex.name, is_default: false })
      .select("id")
      .single();
    if (error || !inserted) continue;
    const rows = ex.items.map((item, i) => ({
      watchlist_id: inserted.id,
      ticker: item.ticker,
      asset_type: item.asset_type,
      notes: item.notes ?? null,
      starred: false,
      position: i
    }));
    if (rows.length > 0) {
      await supabase.from("watchlist_items").insert(rows);
    }
  }
}

/**
 * Get the user's default watchlist, creating it (and seeding starter tickers)
 * on first call.
 */
export async function getOrSeedDefaultWatchlist(
  userId: string
): Promise<{ list: Watchlist; items: WatchlistItem[] }> {
  const supabase = createServerSupabase();

  // Existing default?
  const { data: existing } = await supabase
    .from("watchlists")
    .select("id, name, is_default, created_at")
    .eq("user_id", userId)
    .eq("is_default", true)
    .maybeSingle();

  let list = existing as Watchlist | null;

  if (!list) {
    const { data: inserted, error } = await supabase
      .from("watchlists")
      .insert({ user_id: userId, name: "Core Winners", is_default: true })
      .select("id, name, is_default, created_at")
      .single();
    if (error) throw error;
    list = inserted as Watchlist;

    // Seed items
    const rows = FOUNDER_CORE_WINNERS.map((item, i) => ({
      watchlist_id: list!.id,
      ticker: item.ticker,
      asset_type: "stock",
      notes: item.notes,
      starred: false,
      position: i
    }));
    await supabase.from("watchlist_items").insert(rows);
  }

  const { data: items } = await supabase
    .from("watchlist_items")
    .select("id, ticker, asset_type, notes, starred, position, ethical_override, ethical_override_reason")
    .eq("watchlist_id", list.id)
    .order("position", { ascending: true });

  return { list, items: (items ?? []) as WatchlistItem[] };
}

export async function listWatchlists(userId: string): Promise<
  Array<Watchlist & { item_count: number }>
> {
  const supabase = createServerSupabase();
  const { data: lists } = await supabase
    .from("watchlists")
    .select("id, name, is_default, created_at")
    .eq("user_id", userId)
    .order("created_at", { ascending: true });

  if (!lists || lists.length === 0) return [];

  // Cheap count per watchlist
  const ids = lists.map((l) => l.id);
  const { data: items } = await supabase
    .from("watchlist_items")
    .select("watchlist_id")
    .in("watchlist_id", ids);

  const counts: Record<string, number> = {};
  for (const i of items ?? []) {
    counts[i.watchlist_id] = (counts[i.watchlist_id] ?? 0) + 1;
  }

  return lists.map((l) => ({
    ...(l as Watchlist),
    item_count: counts[l.id] ?? 0
  }));
}

export async function getWatchlist(
  userId: string,
  id: string
): Promise<{ list: Watchlist; items: WatchlistItem[] } | null> {
  const supabase = createServerSupabase();
  const { data: list } = await supabase
    .from("watchlists")
    .select("id, name, is_default, created_at")
    .eq("user_id", userId)
    .eq("id", id)
    .maybeSingle();

  if (!list) return null;

  const { data: items } = await supabase
    .from("watchlist_items")
    .select("id, ticker, asset_type, notes, starred, position, ethical_override, ethical_override_reason")
    .eq("watchlist_id", list.id)
    .order("position", { ascending: true });

  return { list: list as Watchlist, items: (items ?? []) as WatchlistItem[] };
}

export async function createWatchlist(
  userId: string,
  name: string
): Promise<Watchlist> {
  const supabase = createServerSupabase();
  const { data, error } = await supabase
    .from("watchlists")
    .insert({ user_id: userId, name, is_default: false })
    .select("id, name, is_default, created_at")
    .single();
  if (error) throw error;
  return data as Watchlist;
}

export async function renameWatchlist(
  userId: string,
  id: string,
  name: string
): Promise<void> {
  const supabase = createServerSupabase();
  await supabase
    .from("watchlists")
    .update({ name })
    .eq("id", id)
    .eq("user_id", userId);
}

export async function deleteWatchlist(userId: string, id: string): Promise<void> {
  const supabase = createServerSupabase();
  await supabase.from("watchlists").delete().eq("id", id).eq("user_id", userId);
}

export async function addItem(
  userId: string,
  watchlistId: string,
  payload: {
    ticker: string;
    asset_type?: "stock" | "crypto" | "option";
    notes?: string;
    ethical_override?: boolean;
    ethical_override_reason?: string;
  }
): Promise<WatchlistItem> {
  const supabase = createServerSupabase();

  // Confirm the list belongs to this user
  const { data: list } = await supabase
    .from("watchlists")
    .select("id")
    .eq("id", watchlistId)
    .eq("user_id", userId)
    .maybeSingle();
  if (!list) throw new Error("Watchlist not found");

  // Find next position
  const { data: last } = await supabase
    .from("watchlist_items")
    .select("position")
    .eq("watchlist_id", watchlistId)
    .order("position", { ascending: false })
    .limit(1);
  const nextPos = (last?.[0]?.position ?? -1) + 1;

  const { data, error } = await supabase
    .from("watchlist_items")
    .insert({
      watchlist_id: watchlistId,
      ticker: payload.ticker.toUpperCase(),
      asset_type: payload.asset_type ?? "stock",
      notes: payload.notes ?? null,
      starred: false,
      position: nextPos,
      ethical_override: payload.ethical_override ?? false,
      ethical_override_reason: payload.ethical_override_reason ?? null
    })
    .select("id, ticker, asset_type, notes, starred, position, ethical_override, ethical_override_reason")
    .single();
  if (error) throw error;
  return data as WatchlistItem;
}

export async function removeItem(userId: string, itemId: string): Promise<void> {
  const supabase = createServerSupabase();
  const { error } = await supabase
    .from("watchlist_items")
    .delete()
    .eq("id", itemId);
  if (error) throw error;
  void userId;
}

export async function updateItem(
  userId: string,
  itemId: string,
  patch: Partial<Pick<WatchlistItem, "notes" | "starred" | "ethical_override" | "ethical_override_reason">>
): Promise<WatchlistItem | null> {
  const supabase = createServerSupabase();
  const { data, error } = await supabase
    .from("watchlist_items")
    .update(patch)
    .eq("id", itemId)
    .select("id, ticker, asset_type, notes, starred, position, ethical_override, ethical_override_reason")
    .single();
  if (error) throw error;
  void userId;
  return (data as WatchlistItem) ?? null;
}

export async function reorderItem(
  userId: string,
  watchlistId: string,
  itemId: string,
  direction: "up" | "down"
): Promise<void> {
  const supabase = createServerSupabase();
  // Read this item's current position, then swap with the neighbor.
  const { data: cur } = await supabase
    .from("watchlist_items")
    .select("position")
    .eq("id", itemId)
    .eq("watchlist_id", watchlistId)
    .maybeSingle();
  if (!cur) return;
  const curPos = (cur as { position: number }).position;
  const targetPos = direction === "up" ? curPos - 1 : curPos + 1;
  if (targetPos < 0) return;
  // Swap with whatever sits at targetPos.
  const { data: other } = await supabase
    .from("watchlist_items")
    .select("id")
    .eq("watchlist_id", watchlistId)
    .eq("position", targetPos)
    .maybeSingle();
  if (!other) return;
  await supabase
    .from("watchlist_items")
    .update({ position: targetPos })
    .eq("id", itemId);
  await supabase
    .from("watchlist_items")
    .update({ position: curPos })
    .eq("id", (other as { id: string }).id);
  void userId;
}

export async function listWatchlistsWithTickers(
  userId: string
): Promise<{ id: string; name: string; is_default: boolean; tickers: { ticker: string; asset_type: string }[] }[]> {
  const supabase = createServerSupabase();
  const { data: lists } = await supabase
    .from("watchlists")
    .select("id, name, is_default")
    .eq("user_id", userId)
    .order("is_default", { ascending: false })
    .order("created_at", { ascending: true });
  if (!lists) return [];
  const out: { id: string; name: string; is_default: boolean; tickers: { ticker: string; asset_type: string }[] }[] = [];
  for (const wl of lists) {
    const { data: items } = await supabase
      .from("watchlist_items")
      .select("ticker, asset_type")
      .eq("watchlist_id", wl.id)
      .order("position", { ascending: true });
    out.push({
      id: wl.id,
      name: wl.name,
      is_default: wl.is_default,
      tickers: (items ?? []).map((i) => ({ ticker: i.ticker, asset_type: i.asset_type })),
    });
  }
  return out;
}
