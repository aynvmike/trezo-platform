/**
 * Server-only helper for the Allocation Pockets snapshot. Mirrors
 * alpaca-snapshot.ts: one fetch of the agents `/allocations/snapshot`
 * endpoint (the REAL per-market-type budgets the Trade Execution gate
 * enforces), deduped by Next within a request.
 */

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export type SleeveRow = {
  id: string;
  label: string;
  budget_usd: number;
  deployed_usd: number;
  free_usd: number;
  used_pct: number;
  hold: string;
  profit: string;
  layers: string[];
};

export type SleeveSnapshot = {
  configured: boolean;
  profile: string;
  equity_usd: number;
  scaled_max_open: number;
  summary: string;
  sleeves: SleeveRow[];
};

export async function fetchSleeveSnapshot(
  userId: string
): Promise<SleeveSnapshot | null> {
  try {
    const qs = new URLSearchParams({ user_id: userId });
    const r = await fetch(`${AGENTS_BASE}/allocations/snapshot?${qs.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) return null;
    return (await r.json()) as SleeveSnapshot;
  } catch {
    return null;
  }
}
