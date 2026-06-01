import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * POST /api/learning/import
 *
 * Accepts the user's own trade history and writes it into
 * `trade_outcomes` so the learning loop sees real-world trades, not
 * only the bot's paper trades.
 *
 * Body shape (JSON):
 *   { rows: [ { ticker, side?, strategy?, entry_price, exit_price,
 *               quantity?, realized_pnl_usd?, opened_at?, closed_at?,
 *               exit_reason?, notes? }, ... ] }
 *
 * OR a single object { rows: [oneRow] } — same shape, length 1.
 *
 * The route computes realized_pnl_usd when the user didn't supply
 * one (qty * (exit - entry) with sign flipped for shorts). It tags
 * every row source_table='manual_import' so the learning panel can
 * tell user-supplied data from bot-recorded data later if needed.
 *
 * RLS handles isolation — the policy on trade_outcomes only accepts
 * inserts where user_id = auth.uid(). The route forces user_id from
 * the session, so a stray user_id in the payload can't escape.
 */
type InRow = {
  ticker?: string;
  side?: string;
  strategy?: string;
  direction?: string;
  entry_price?: number | string;
  exit_price?: number | string;
  quantity?: number | string;
  realized_pnl_usd?: number | string;
  opened_at?: string;
  closed_at?: string;
  exit_reason?: string;
  notes?: string;
  tcs_at_entry?: number | string;
  iv_environment_at_entry?: string;
  regime_at_entry?: string;
};

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function calcPnL(side: string, entry: number, exit: number, qty: number) {
  if (side === "short") return qty * (entry - exit);
  return qty * (exit - entry);
}

export async function POST(req: Request) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." },
                             { status: 401 });
  }

  let body: { rows?: InRow[] } = {};
  try {
    body = (await req.json()) as { rows?: InRow[] };
  } catch {
    return NextResponse.json({ ok: false, error: "Body must be JSON." },
                             { status: 400 });
  }

  const rows = Array.isArray(body.rows) ? body.rows : [];
  if (rows.length === 0) {
    return NextResponse.json({ ok: false, error: "No rows in payload." },
                             { status: 400 });
  }
  if (rows.length > 500) {
    return NextResponse.json(
      { ok: false, error: "Max 500 rows per import. Split your CSV." },
      { status: 400 }
    );
  }

  const out: Record<string, unknown>[] = [];
  const errors: { index: number; reason: string }[] = [];

  rows.forEach((r, i) => {
    const ticker = (r.ticker || "").trim().toUpperCase();
    if (!ticker) {
      errors.push({ index: i, reason: "ticker required" });
      return;
    }
    const side = (r.side || "long").trim().toLowerCase();
    if (side !== "long" && side !== "short") {
      errors.push({ index: i, reason: `side must be long/short (got ${r.side})` });
      return;
    }
    const entry = num(r.entry_price);
    const exit = num(r.exit_price);
    const qty = num(r.quantity) ?? 1;
    let pnl = num(r.realized_pnl_usd);
    if (pnl === null) {
      if (entry === null || exit === null) {
        errors.push({
          index: i,
          reason:
            "need realized_pnl_usd OR (entry_price + exit_price + quantity)",
        });
        return;
      }
      pnl = calcPnL(side, entry, exit, qty);
    }

    let opened: string | null = r.opened_at?.trim() || null;
    let closed: string | null = r.closed_at?.trim() || null;
    // Best-effort hold_minutes computed below
    let hold: number | null = null;
    if (opened && closed) {
      try {
        const a = new Date(opened).getTime();
        const b = new Date(closed).getTime();
        if (Number.isFinite(a) && Number.isFinite(b) && b >= a) {
          hold = Math.max(0, Math.round((b - a) / 60_000));
          opened = new Date(a).toISOString();
          closed = new Date(b).toISOString();
        }
      } catch {
        // leave as supplied
      }
    }

    out.push({
      user_id: user.id,
      source_table: "manual_import",
      ticker,
      asset_type: null,
      side,
      strategy: (r.strategy || "manual").trim() || "manual",
      direction: r.direction ?? (side === "short" ? "bearish" : "bullish"),
      tcs_at_entry: num(r.tcs_at_entry),
      iv_environment_at_entry: r.iv_environment_at_entry || null,
      regime_at_entry: r.regime_at_entry || null,
      entry_price: entry,
      exit_price: exit,
      quantity: qty,
      realized_pnl_usd: pnl,
      exit_reason: r.exit_reason || "manual_import",
      status: pnl > 0 ? "closed_target" : pnl < 0 ? "closed_stop" : "closed_manual",
      opened_at: opened,
      closed_at: closed,
      hold_minutes: hold,
      entry_payload: r.notes ? { notes: r.notes } : null,
    });
  });

  if (out.length === 0) {
    return NextResponse.json(
      { ok: false, error: "Every row had a problem.", errors },
      { status: 400 }
    );
  }

  const { error } = await supabase.from("trade_outcomes").insert(out);
  if (error) {
    return NextResponse.json(
      { ok: false, error: error.message, errors },
      { status: 500 }
    );
  }

  return NextResponse.json({
    ok: true,
    inserted: out.length,
    skipped: errors.length,
    errors,
  });
}

/**
 * GET /api/learning/import — returns the simple CSV column reference
 * so the import UI can show the format inline without duplicating it.
 */
export async function GET() {
  return NextResponse.json({
    ok: true,
    required: ["ticker", "entry_price", "exit_price"],
    recommended: ["side", "strategy", "quantity", "opened_at", "closed_at"],
    optional: [
      "realized_pnl_usd",
      "exit_reason",
      "notes",
      "tcs_at_entry",
      "iv_environment_at_entry",
      "regime_at_entry",
      "direction",
    ],
    notes: [
      "If you skip realized_pnl_usd, the route computes it from (exit - entry) * quantity (sign-aware for short).",
      "Dates accept ISO 8601 (2026-04-15T14:30:00Z) or any format JS Date() can parse.",
      "Strategy is free-text — use whatever label you'd want to group your trades by in the Learning Insights table.",
      "Max 500 rows per request.",
    ],
  });
}
