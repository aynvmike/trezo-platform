import { createClient } from "@/lib/supabase/server";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type Rotation = {
  trim_ticker: string;
  trim_position_id: string;
  trim_current_tcs: number;
  take_ticker: string;
  take_tcs: number;
  gap: number;
  raised_at: string;
};

type Stalled = {
  position_id: string;
  ticker: string;
  notional_usd: number;
  recommendation: string;
  current_tcs: number;
  entry_tcs: number;
};

type Response = {
  ok: boolean;
  locked_usd?: number;
  stalled_positions?: Stalled[];
  rotations?: Rotation[];
  waiting_count?: number;
  error?: string;
};

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/**
 * CapitalPressurePanel - surfaces the asymmetry between locked-in
 * stalled winners and waiting higher-TCS opportunities. Mike's
 * capital recycling concept made visible at a glance.
 *
 * Renders nothing when there's no locked capital AND no waiting
 * rotations - the page stays clean when nothing needs your eyes.
 */
export async function CapitalPressurePanel({ userId }: { userId: string }) {
  let data: Response | null = null;
  try {
    const r = await fetch(
      `${AGENTS_BASE}/learning/capital-pressure?user_id=${encodeURIComponent(userId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(8000) }
    );
    if (r.ok) data = (await r.json()) as Response;
  } catch {
    data = null;
  }
  if (!data?.ok) return null;
  const locked = data.locked_usd ?? 0;
  const rotations = data.rotations ?? [];
  const stalled = data.stalled_positions ?? [];
  if (locked === 0 && rotations.length === 0) return null;

  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3">
      <div>
        <h2 className="text-xs font-medium uppercase tracking-widest text-amber-900">
          Capital pressure
        </h2>
        <p className="text-sm text-amber-900 leading-relaxed mt-1">
          {locked > 0 ? (
            <>
              <span className="font-medium font-mono">{usd(locked)}</span>{" "}
              locked in {stalled.length} stalled{" "}
              {stalled.length === 1 ? "position" : "positions"}.
            </>
          ) : null}{" "}
          {rotations.length > 0 ? (
            <>
              {rotations.length} higher-TCS{" "}
              {rotations.length === 1 ? "signal was" : "signals were"}{" "}
              vetoed in the last 24 hours because the open-position cap
              was hit.
            </>
          ) : null}
        </p>
      </div>

      {rotations.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-widest text-amber-900/80">
            Suggested rotations
          </p>
          <ul className="space-y-1 text-xs">
            {rotations.map((r) => (
              <li
                key={r.trim_position_id + r.raised_at}
                className="flex items-baseline justify-between gap-3 rounded border border-amber-200 bg-white/60 px-2 py-1.5"
              >
                <span className="text-amber-900">
                  Trim{" "}
                  <span className="font-mono font-medium">{r.trim_ticker}</span>{" "}
                  (TCS {r.trim_current_tcs}) to take{" "}
                  <span className="font-mono font-medium">{r.take_ticker}</span>{" "}
                  (TCS {r.take_tcs}, +{r.gap} gap)
                </span>
                <span className="text-[10px] text-amber-900/70 whitespace-nowrap">
                  {new Date(r.raised_at).toLocaleTimeString()}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-amber-900/70 italic">
            Suggestions only. Use the Exit Advisor&apos;s Trim ▾ button
            on each position to act.
          </p>
        </div>
      ) : null}

      {stalled.length > 0 && rotations.length === 0 ? (
        <p className="text-xs text-amber-900/80">
          No higher-TCS signals waiting yet. The locked positions are
          watched by the Exit Advisor and a thesis-decayed alert will
          appear when they qualify.
        </p>
      ) : null}
    </section>
  );
}
