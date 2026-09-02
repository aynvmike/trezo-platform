/**
 * Server-side helpers for paper trading data.
 *
 * PAGES-03: every list helper returns `null` when the read itself
 * failed (logged server-side) and `[]` only when the table is genuinely
 * empty. Callers must branch on null rather than treating it as empty.
 */

import { createClient } from "@/lib/supabase/server";
import { loadResult, type LoadResult } from "@/components/dashboard/load-error";

export type PaperAccount = {
  user_id: string;
  starting_capital_usd: number;
  current_cash_usd: number;
  vault_balance_usd: number;
  ytd_realized_pnl_usd: number;
  today_realized_pnl_usd: number;
  daily_target_hit_today: boolean;
  last_reset_date: string;
};

export type PaperPosition = {
  id: string;
  ticker: string;
  asset_type: "stock" | "crypto" | "option";
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  entry_at: string;
  stop_price: number | null;
  target_price: number | null;
  status: "open" | "closed_stop" | "closed_target" | "closed_manual" | "closed_time" | "closed_eod";
  exit_price: number | null;
  exit_at: string | null;
  realized_pnl_usd: number | null;
  strategy: string | null;
  broker: string | null;
  close_requested: boolean | null;
};

export type VaultTx = {
  id: string;
  amount_usd: number;
  kind: "profit_lock" | "manual_withdrawal" | "manual_deposit" | "reset";
  description: string | null;
  created_at: string;
};

/**
 * One BOOK's paper account (`bookKey` = trading_accounts.account_key, which
 * is what `paper_accounts.user_id` holds since 0047).
 *
 * rv:web-pages (:50): this used to collapse "read failed" and "no row yet"
 * into one null, contradicting the module header. It now returns a
 * LoadResult: `failure` set when the read failed (logged), otherwise
 * `data` is the row or null when the book has no account row yet.
 */
export async function getPaperAccount(bookKey: string): Promise<LoadResult<PaperAccount | null>> {
  const supabase = createClient();
  const res = await supabase
    .from("paper_accounts")
    .select("*")
    .eq("user_id", bookKey)
    .maybeSingle();
  return loadResult<PaperAccount | null>("paper_accounts", res as { data: PaperAccount | null; error: { message: string } | null });
}

export async function getOpenPositions(userId: string): Promise<PaperPosition[] | null> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("paper_positions")
    .select("*")
    .eq("user_id", userId)
    .eq("status", "open")
    .order("entry_at", { ascending: false });
  if (error) {
    console.error(`[load] paper_positions: ${error.message}`);
    return null;
  }
  return (data ?? []) as PaperPosition[];
}

export async function getClosedPositions(
  userId: string,
  limit = 25
): Promise<PaperPosition[] | null> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("paper_positions")
    .select("*")
    .eq("user_id", userId)
    .neq("status", "open")
    .order("exit_at", { ascending: false })
    .limit(limit);
  if (error) {
    console.error(`[load] paper_positions: ${error.message}`);
    return null;
  }
  const rows = (data ?? []) as PaperPosition[];
  // Hide reconciler "ghost" rows: an empty/errored broker read used to
  // phantom-close real positions as closed_manual with a null exit_price
  // and $0 P&L. Genuine manual closes always carry a real exit_price, so
  // they are unaffected (open-bell phantom-close race, 2026-06-15).
  return rows.filter(
    (p) =>
      !(
        p.status === "closed_manual" &&
        (p.exit_price === null || p.exit_price === undefined) &&
        Number(p.realized_pnl_usd ?? 0) === 0
      )
  );
}

export async function getVaultTransactions(
  userId: string,
  limit = 25
): Promise<VaultTx[] | null> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("paper_vault_transactions")
    .select("*")
    .eq("user_id", userId)
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) {
    console.error(`[load] paper_vault_transactions: ${error.message}`);
    return null;
  }
  return (data ?? []) as VaultTx[];
}
