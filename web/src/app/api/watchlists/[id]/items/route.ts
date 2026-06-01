import { NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { addItem } from "@/lib/watchlists";
import { checkTicker, logOverride } from "@/lib/services/ethical";

export const dynamic = "force-dynamic";

const itemSchema = z.object({
  ticker: z.string().min(1).max(12),
  asset_type: z.enum(["stock", "crypto", "option"]).optional(),
  notes: z.string().max(500).optional(),
  override: z.boolean().optional(),
  override_reason: z.string().max(500).optional()
});

/**
 * POST /api/watchlists/[id]/items
 *
 * Adds a ticker. Runs the ethical filter first.
 *
 * - If the ticker passes, returns 201 + the new item.
 * - If it fails AND is overridable AND `override === true`, logs the
 *   override, marks the item, returns 201.
 * - If it fails AND is overridable BUT `override !== true`, returns 409
 *   with the decision so the UI can show the override dialog.
 * - If it fails AND is NOT overridable (Tier 1), returns 403.
 */
export async function POST(request: Request, { params }: { params: { id: string } }) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  try {
    const body = itemSchema.parse(await request.json());
    const decision = await checkTicker(user.id, body.ticker);

    if (!decision.ok) {
      if (!decision.overridable) {
        return NextResponse.json(
          {
            error: "blocked",
            decision
          },
          { status: 403 }
        );
      }
      if (!body.override) {
        return NextResponse.json(
          {
            error: "blocked_overridable",
            decision
          },
          { status: 409 }
        );
      }
      // Override path
      const reason = body.override_reason?.trim();
      if (!reason || reason.length < 4) {
        return NextResponse.json(
          { error: "override_reason_required", decision },
          { status: 400 }
        );
      }
      await logOverride(user.id, body.ticker, decision.category, decision.tier, reason);
      const item = await addItem(user.id, params.id, {
        ticker: body.ticker,
        asset_type: body.asset_type,
        notes: body.notes,
        ethical_override: true,
        ethical_override_reason: reason
      });
      return NextResponse.json({ item }, { status: 201 });
    }

    const item = await addItem(user.id, params.id, {
      ticker: body.ticker,
      asset_type: body.asset_type,
      notes: body.notes
    });
    return NextResponse.json({ item }, { status: 201 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Invalid request";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
