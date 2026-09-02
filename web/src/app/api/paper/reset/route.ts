import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getOwnerBookKeys, resolveBookKey } from "@/lib/books";

export const dynamic = "force-dynamic";

/**
 * POST /api/paper/reset
 *
 * Resets ONE paper book to a target starting equity. Closes every open
 * paper position in that book (so the agents start from a clean slate),
 * zeroes YTD / today's realized P&L, and writes a "reset" vault
 * transaction so the change is auditable.
 *
 * Body: { target_equity_usd: number, account_key?: string }
 *
 * rv:web-pages (:77): `user_id` on the book tables is the BOOK key (0047),
 * so scoping by the auth uid reset only the book whose key equals it and
 * never books 2/3. The book is now resolved from the owner's active
 * trading_accounts: `account_key` when given (must be theirs), else their
 * own key when it is a book, else their only book -- never a guess.
 *
 * The point of this is purely for testing — Mike wants to see how the
 * agents behave with $1k vs $5k vs $100k. The posture map in the
 * allocation engine (growth / balanced / income) reads the new equity
 * automatically; nothing else needs to be told.
 */
export async function POST(request: Request) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  let body: { target_equity_usd?: number; equity?: number; account_key?: string };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return NextResponse.json(
      { error: "Bad request body — expected JSON." },
      { status: 400 }
    );
  }

  // MIG-03 (found while fixing the audit row): the only caller,
  // components/dashboard/account-size-sim.tsx, posts `{ equity }`, so
  // `target_equity_usd` was always undefined and every reset 400'd.
  // Accept both spellings.
  const target = Number(body.target_equity_usd ?? body.equity);
  if (!Number.isFinite(target) || target < 100 || target > 10_000_000) {
    return NextResponse.json(
      {
        error:
          "Target equity must be between $100 and $10,000,000."
      },
      { status: 400 }
    );
  }

  // 0. Which book? Never the primary by default -- see lib/books.ts.
  const books = await getOwnerBookKeys(supabase, user.id);
  if (books.failure) {
    return NextResponse.json(
      { error: `Could not resolve your books: ${books.failure.message}` },
      { status: 500 }
    );
  }
  const bookKey = resolveBookKey(books.data, user.id, body.account_key);
  if (!bookKey) {
    return NextResponse.json(
      { error: "Book not resolvable: pass account_key (one of your active trading accounts)." },
      { status: 400 }
    );
  }

  // 1. Close every open paper position in that book. We mark them
  //    closed_manual with no realized P&L — the account is being reset,
  //    not exited at a market price.
  const { error: closeErr } = await supabase
    .from("paper_positions")
    .update({
      status: "closed_manual",
      exit_at: new Date().toISOString(),
      realized_pnl_usd: 0
    })
    .eq("user_id", bookKey)
    .eq("status", "open");
  if (closeErr) {
    return NextResponse.json(
      { error: `Could not close open positions: ${closeErr.message}` },
      { status: 500 }
    );
  }

  // 2. Reset the account row. starting_capital_usd gets the new target
  //    too, so all percentage views start at the new baseline.
  const today = new Date().toISOString().slice(0, 10);
  // rv:web-pages (:77a): an UPDATE that matches zero rows is not an error,
  // so the "row didn't exist yet — create it" branch below was dead code.
  // Select the touched rows back to know whether anything was reset.
  const { data: updated, error: acctErr } = await supabase
    .from("paper_accounts")
    .update({
      starting_capital_usd: target,
      current_cash_usd: target,
      vault_balance_usd: 0,
      ytd_realized_pnl_usd: 0,
      today_realized_pnl_usd: 0,
      daily_target_hit_today: false,
      last_reset_date: today
    })
    .eq("user_id", bookKey)
    .select("user_id");
  if (acctErr) {
    return NextResponse.json(
      { error: `Could not reset paper account: ${acctErr.message}` },
      { status: 500 }
    );
  }
  if (!updated || updated.length === 0) {
    // Account row didn't exist yet — create it for this book.
    const { error: insErr } = await supabase
      .from("paper_accounts")
      .insert({
        user_id: bookKey,
        starting_capital_usd: target,
        current_cash_usd: target
      });
    if (insErr) {
      return NextResponse.json(
        { error: `Could not create paper account: ${insErr.message}` },
        { status: 500 }
      );
    }
  }

  // 3. Audit the reset.
  // MIG-03: the column is `description` (0008_paper_trading.sql), not
  // `note`, and the insert error used to be discarded — so no reset was
  // ever audited. Check it like the sibling writes above. The reset
  // itself has already applied by this point; say so in the error.
  const { error: auditErr } = await supabase
    .from("paper_vault_transactions")
    .insert({
      user_id: bookKey,
      amount_usd: target,
      kind: "reset",
      description: `Paper account reset to $${target.toLocaleString()} for testing`
    });
  if (auditErr) {
    console.error(`[paper/reset] audit insert failed: ${auditErr.message}`);
    return NextResponse.json(
      {
        error: `Account was reset to $${target.toLocaleString()}, but the audit entry could not be written: ${auditErr.message}`
      },
      { status: 500 }
    );
  }

  return NextResponse.json({
    ok: true,
    account_key: bookKey,
    equity_usd: target,
    reset_at: new Date().toISOString()
  });
}
