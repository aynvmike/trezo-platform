import { createClient } from "@/lib/supabase/server";
import { holdingTerm, type ClosedPosition } from "@/lib/tax";

export const dynamic = "force-dynamic";

/**
 * GET /api/tax/export
 * Exports all closed positions as a Schedule-D / 1099-B-style CSV.
 * Columns mirror IRS Form 8949: description, date acquired, date sold,
 * proceeds, cost basis, gain/loss, term.
 */
export async function GET() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return new Response("Unauthorized", { status: 401 });
  }

  const { data } = await supabase
    .from("paper_positions")
    .select("id, ticker, side, quantity, entry_price, entry_at, exit_price, exit_at, realized_pnl_usd, status")
    .eq("user_id", user.id)
    .neq("status", "open")
    .order("exit_at", { ascending: true });

  const positions = (data ?? []) as ClosedPosition[];

  const header = [
    "Description",
    "Date Acquired",
    "Date Sold",
    "Quantity",
    "Proceeds (USD)",
    "Cost Basis (USD)",
    "Gain/Loss (USD)",
    "Term"
  ];

  const rows = positions.map((p) => {
    const qty = Number(p.quantity);
    const entry = Number(p.entry_price);
    const exit = Number(p.exit_price ?? 0);
    const costBasis = qty * entry;
    const proceeds = qty * exit;
    const gain = Number(p.realized_pnl_usd ?? 0);
    const term = holdingTerm(p.entry_at, p.exit_at);
    const acq = new Date(p.entry_at).toLocaleDateString("en-US");
    const sold = p.exit_at ? new Date(p.exit_at).toLocaleDateString("en-US") : "";
    return [
      `${qty} ${p.ticker} (paper)`,
      acq,
      sold,
      String(qty),
      proceeds.toFixed(2),
      costBasis.toFixed(2),
      gain.toFixed(2),
      term === "long" ? "Long-term" : "Short-term"
    ];
  });

  const csv = [header, ...rows]
    .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
    .join("\r\n");

  const today = new Date().toISOString().slice(0, 10);
  return new Response(csv, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="trezo-schedule-d-${today}.csv"`
    }
  });
}
