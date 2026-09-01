import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type AgentsResp = {
  ok: boolean;
  error?: string;
  routed?: string;
  leg?: "wheel_csp" | "wheel_cc";
  occ?: string;
  underlying?: string;
  strike?: number;
  expiration?: string;
  premium?: number;
  alpaca_order_id?: string;
  alpaca_order_status?: string;
};

/**
 * POST /api/wheel/place-leg
 * Body: { leg: "csp" | "cc", underlying, target_strike, target_exp, contracts?, limit_price? }
 *
 * Owner-gated. Resolves the user_id from the Supabase session, then
 * proxies to the agents service. The agents service uses the user's
 * OAuth Alpaca connection when present.
 *
 * After a successful Alpaca placement, this route ALSO inserts a row
 * into `options_positions` (asset_type income, status open) so the
 * Wheel page's modeled planner stays coherent with what was actually
 * placed. The insert is best-effort — a failed insert never blocks
 * the placement reply, but `recorded` / `record_error` are surfaced
 * so the UI can show what happened.
 */
export async function POST(request: Request) {
  // ADM-04: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;
  const user = guard.user;

  let body: {
    leg?: string;
    underlying?: string;
    target_strike?: number;
    target_exp?: string;
    contracts?: number;
    limit_price?: number | null;
  };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return NextResponse.json(
      { ok: false, error: "Bad request body — expected JSON." },
      { status: 400 }
    );
  }

  const leg = (body.leg ?? "").trim().toLowerCase();
  if (leg !== "csp" && leg !== "cc") {
    return NextResponse.json(
      { ok: false, error: "leg must be 'csp' or 'cc'." },
      { status: 400 }
    );
  }
  const underlying = (body.underlying ?? "").trim().toUpperCase();
  if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(underlying)) {
    return NextResponse.json(
      { ok: false, error: "Invalid underlying ticker." },
      { status: 400 }
    );
  }
  const target_strike = Number(body.target_strike);
  if (!Number.isFinite(target_strike) || target_strike <= 0) {
    return NextResponse.json(
      { ok: false, error: "target_strike must be a positive number." },
      { status: 400 }
    );
  }
  const target_exp = String(body.target_exp ?? "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(target_exp)) {
    return NextResponse.json(
      { ok: false, error: "target_exp must be ISO date (YYYY-MM-DD)." },
      { status: 400 }
    );
  }
  const contracts = Math.max(1, Math.min(50, Math.round(Number(body.contracts ?? 1))));
  const limit_price =
    body.limit_price && Number.isFinite(Number(body.limit_price))
      ? Number(body.limit_price)
      : undefined;

  let agentsResp: AgentsResp;
  try {
    const qs = new URLSearchParams({
      user_id: user.id,
      leg,
      underlying,
      target_strike: String(target_strike),
      target_exp,
      contracts: String(contracts),
      ...(limit_price !== undefined ? { limit_price: String(limit_price) } : {})
    });
    const r = await fetch(`${AGENTS_BASE}/wheel/place-leg?${qs.toString()}`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(20_000)
    });
    agentsResp = (await r.json()) as AgentsResp;
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      { ok: false, error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }

  // Auto-record into options_positions on a successful placement.
  let recorded = false;
  let record_error: string | undefined;
  if (agentsResp.ok && agentsResp.strike && agentsResp.expiration) {
    try {
      const optionType = leg === "csp" ? "put" : "call";
      const strategy = leg === "csp" ? "wheel_csp" : "wheel_cc";
      // Premium per share × 100 shares per contract × contracts.
      // Positive because sell-to-open is a credit received.
      const premiumPerShare = Number(agentsResp.premium ?? limit_price ?? 0);
      const netPremium = Math.round(premiumPerShare * 100 * contracts * 100) / 100;
      const noteBits = [
        `Placed via Alpaca (${agentsResp.routed ?? "?"})`,
        agentsResp.alpaca_order_id ? `order ${agentsResp.alpaca_order_id}` : null,
        agentsResp.alpaca_order_status ? `status=${agentsResp.alpaca_order_status}` : null,
        agentsResp.occ ? `occ=${agentsResp.occ}` : null
      ]
        .filter(Boolean)
        .join(" · ");

      const { error } = await supabase.from("options_positions").insert({
        user_id: user.id,
        underlying: agentsResp.underlying ?? underlying,
        strategy,
        direction: "income",
        option_type: optionType,
        strike: agentsResp.strike,
        expiration: agentsResp.expiration,
        contracts,
        net_premium_usd: netPremium,
        legs: [],
        status: "open",
        notes: noteBits || null
      });
      if (error) {
        record_error = error.message;
      } else {
        recorded = true;
      }
    } catch (e) {
      record_error = e instanceof Error ? e.message : "insert failed";
    }
  }

  return NextResponse.json({ ...agentsResp, recorded, record_error });
}
