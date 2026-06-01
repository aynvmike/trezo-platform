import { cn } from "@/lib/utils";
import { WheelPlaceButton } from "@/components/dashboard/wheel-place-button";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type Leg = {
  occ: string;
  strike: number;
  expiration: string;
  premium: number;
} | null;

type Row = {
  symbol: string;
  spot?: number;
  csp?: Leg;
  cc?: Leg;
  error?: string;
};

type Snap = {
  configured: boolean;
  broker?: string;       // 'alpaca' | 'webull' | 'modeled' — provider-agnostic
  note?: string;
  as_of?: string;
  rows?: Row[];
};

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  });
}

/**
 * Live wheel-pricing panel. Fetches the agents' /wheel/live-quotes
 * endpoint for the wheel watchlist and shows the live CSP + CC
 * premiums next to spot. When Alpaca isn't configured, the panel
 * quietly explains and the modeled prices below remain the only
 * view.
 */
export async function WheelLiveQuotes({
  underlyings
}: {
  underlyings: string[];
}) {
  const qs = encodeURIComponent(underlyings.join(","));
  let snap: Snap | null = null;
  try {
    const r = await fetch(`${AGENTS_BASE}/wheel/live-quotes?underlyings=${qs}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    if (r.ok) snap = (await r.json()) as Snap;
  } catch {
    snap = null;
  }
  if (!snap) return null;
  if (!snap.configured) {
    return (
      <section className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-4 text-sm text-weave-600">
        <p className="font-medium text-weave-800">Live options pricing — no broker connected</p>
        <p className="beginner-only mt-1 leading-relaxed">
          Connect a broker (Alpaca today; Webull and Robinhood soon) on
          Settings → Connections to switch the Wheel from modeled
          Black-Scholes premiums to live bid/ask off the real options
          chain. Modeled prices below stay in effect until then.
        </p>
      </section>
    );
  }
  const brokerName = snap.broker || "alpaca";
  const rows = snap.rows ?? [];
  const liveCount = rows.filter((r) => r.csp || r.cc).length;
  const asOf = snap.as_of ? new Date(snap.as_of).toLocaleString() : "";

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Live wheel pricing
          </h2>
          <p className="text-xs text-weave-500">
            Live mid premium via{" "}
            <span className="font-medium capitalize">{brokerName}</span>{" "}
            options chain · {liveCount} of {rows.length} names with a
            live read · refreshed {asOf}
          </p>
        </div>
        <span className="text-[10px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5">
          LIVE · {brokerName}
        </span>
      </div>
      <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3 text-right">Spot</th>
              <th className="px-4 py-3">Cash-secured put</th>
              <th className="px-4 py-3 text-right">Put premium</th>
              <th className="px-4 py-3">Covered call</th>
              <th className="px-4 py-3 text-right">Call premium</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol} className="border-b border-weave-50 last:border-0">
                <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
                  {r.symbol}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {r.spot ? usd(r.spot) : "—"}
                </td>
                <td className="px-4 py-2.5 text-xs text-weave-500">
                  {r.csp ? (
                    <>
                      <span className="font-mono text-weave-700">
                        ${r.csp.strike.toFixed(2)}
                      </span>{" "}
                      · exp {r.csp.expiration}
                    </>
                  ) : (
                    <span className="text-amber-700">
                      {r.error ?? "No live quote"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-emerald-700">
                  {r.csp ? (
                    <>
                      <div>{usd(r.csp.premium * 100)}</div>
                      <div className="mt-1">
                        <WheelPlaceButton
                          leg="csp"
                          underlying={r.symbol}
                          targetStrike={r.csp.strike}
                          targetExp={r.csp.expiration}
                          premium={r.csp.premium}
                        />
                      </div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2.5 text-xs text-weave-500">
                  {r.cc ? (
                    <>
                      <span className="font-mono text-weave-700">
                        ${r.cc.strike.toFixed(2)}
                      </span>{" "}
                      · exp {r.cc.expiration}
                    </>
                  ) : (
                    <span className="text-amber-700">
                      {r.csp ? "No live call quote" : ""}
                    </span>
                  )}
                </td>
                <td
                  className={cn(
                    "px-4 py-2.5 text-right font-mono",
                    r.cc ? "text-emerald-700" : "text-weave-400"
                  )}
                >
                  {r.cc ? (
                    <>
                      <div>{usd(r.cc.premium * 100)}</div>
                      <div className="mt-1">
                        <WheelPlaceButton
                          leg="cc"
                          underlying={r.symbol}
                          targetStrike={r.cc.strike}
                          targetExp={r.cc.expiration}
                          premium={r.cc.premium}
                        />
                      </div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        Premium shown per contract (premium × 100 shares). The modeled
        per-cycle premium below remains the planner; live pricing is
        the reality check before the bot opens a real position. Names
        with &ldquo;No live quote&rdquo; either have thin options
        chains or the indicative feed did not return a bid/ask this
        tick — the modeled price keeps the page useful in the meantime.
      </p>
    </section>
  );
}
