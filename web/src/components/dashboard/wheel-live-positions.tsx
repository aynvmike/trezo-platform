import { cn } from "@/lib/utils";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type OptionRow = {
  occ: string;
  underlying: string;
  type: "call" | "put" | string;
  strike: number;
  expiration: string;
  contracts: number;
  side: string;
  leg: "wheel_csp" | "wheel_cc" | "long_option" | string;
  avg_entry_price: number;
  market_value: number;
  unrealized_pl: number;
  net_premium_usd: number;
};

type EquityRow = {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  market_value: number;
  unrealized_pl: number;
};

type Snap = {
  configured: boolean;
  routed?: string;
  options?: OptionRow[];
  equity?: EquityRow[];
  as_of?: string;
  note?: string;
};

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  });
}

const LEG_LABEL: Record<string, string> = {
  wheel_csp: "Cash-secured put",
  wheel_cc: "Covered call",
  long_option: "Long option"
};

const LEG_PILL: Record<string, string> = {
  wheel_csp: "bg-weave-100 text-weave-800",
  wheel_cc: "bg-treasure-100 text-treasure-700",
  long_option: "bg-amber-100 text-amber-800"
};

/**
 * Real options positions from the user's connected Alpaca account.
 * Sits alongside the modeled-planner section below so the user can
 * compare what the bot planned to do vs what actually lives in the
 * broker. When the account isn't connected, the component renders
 * a quiet hint pointing at Settings → Connections.
 */
export async function WheelLivePositions({
  userId
}: {
  userId: string;
}) {
  const qs = new URLSearchParams({ user_id: userId }).toString();
  let snap: Snap | null = null;
  try {
    const r = await fetch(`${AGENTS_BASE}/wheel/positions?${qs}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    if (r.ok) snap = (await r.json()) as Snap;
  } catch {
    snap = null;
  }
  if (!snap) return null;

  if (!snap.configured) {
    return (
      <section className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-4 text-sm text-weave-600">
        <p className="font-medium text-weave-800">
          Live Wheel positions — Alpaca not connected
        </p>
        <p className="beginner-only mt-1 leading-relaxed">
          Connect Alpaca on{" "}
          <a
            href="/dashboard/settings/connections"
            className="underline hover:text-weave-700"
          >
            Settings → Connections
          </a>{" "}
          to read the real options positions in your account. Until
          then the Wheel page shows the modeled planner below; nothing
          is wrong.
        </p>
      </section>
    );
  }

  const options = snap.options ?? [];
  const equity = snap.equity ?? [];
  const csps = options.filter((o) => o.leg === "wheel_csp");
  const ccs = options.filter((o) => o.leg === "wheel_cc");
  const others = options.filter(
    (o) => o.leg !== "wheel_csp" && o.leg !== "wheel_cc"
  );
  const totalUnrealized = options.reduce(
    (a, o) => a + (o.unrealized_pl || 0),
    0
  );
  const totalPremium = options.reduce(
    (a, o) => a + (o.net_premium_usd || 0),
    0
  );
  const asOf = snap.as_of ? new Date(snap.as_of).toLocaleString() : "";

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Live Wheel positions
          </h2>
          <p className="text-xs text-weave-500">
            Real options legs from your Alpaca account · routed via{" "}
            {snap.routed === "user-oauth" ? "your OAuth connection" : "service keys"} ·
            refreshed {asOf}
          </p>
        </div>
        <span className="text-[10px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5">
          LIVE
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Cash-secured puts" value={String(csps.length)} />
        <Stat label="Covered calls" value={String(ccs.length)} />
        <Stat
          label="Premium at work"
          value={usd(totalPremium)}
          tone={totalPremium > 0 ? "good" : "neutral"}
        />
        <Stat
          label="Unrealized P&L"
          value={`${totalUnrealized >= 0 ? "+" : ""}${usd(totalUnrealized)}`}
          tone={totalUnrealized >= 0 ? "good" : "bad"}
        />
      </div>

      {options.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-4 text-sm text-weave-500">
          No open options positions on the account. The modeled planner
          below shows what the bot WOULD open next.
        </div>
      ) : (
        <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Leg</th>
                <th className="px-4 py-3 text-right">Strike</th>
                <th className="px-4 py-3 text-right">Contracts</th>
                <th className="px-4 py-3 text-right">Premium @ entry</th>
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3 text-right">Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {[...csps, ...ccs, ...others].map((o) => (
                <tr key={o.occ} className="border-b border-weave-50 last:border-0">
                  <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
                    {o.underlying}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={cn(
                        "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                        LEG_PILL[o.leg] ?? "bg-weave-50 text-weave-500"
                      )}
                    >
                      {LEG_LABEL[o.leg] ?? o.leg}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    ${o.strike.toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {o.contracts}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-emerald-700">
                    {usd(o.net_premium_usd)}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-weave-500">
                    {o.expiration}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2.5 text-right font-mono",
                      o.unrealized_pl >= 0 ? "text-emerald-700" : "text-red-700"
                    )}
                  >
                    {o.unrealized_pl >= 0 ? "+" : ""}
                    {usd(o.unrealized_pl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {equity.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-widest text-weave-500">
            Equity holdings ({equity.length})
          </p>
          <p className="beginner-only text-xs text-weave-500 leading-relaxed">
            Long stock positions that may be the result of an
            assignment — these are what the bot writes covered calls
            against.
          </p>
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-2">Symbol</th>
                  <th className="px-4 py-2 text-right">Shares</th>
                  <th className="px-4 py-2 text-right">Avg entry</th>
                  <th className="px-4 py-2 text-right">Market value</th>
                  <th className="px-4 py-2 text-right">Unrealized</th>
                </tr>
              </thead>
              <tbody>
                {equity.map((e) => (
                  <tr key={e.symbol} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-2 font-mono font-medium text-weave-800">
                      {e.symbol}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">{e.qty}</td>
                    <td className="px-4 py-2 text-right font-mono text-weave-500">
                      {usd(e.avg_entry_price)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {usd(e.market_value)}
                    </td>
                    <td
                      className={cn(
                        "px-4 py-2 text-right font-mono",
                        e.unrealized_pl >= 0 ? "text-emerald-700" : "text-red-700"
                      )}
                    >
                      {e.unrealized_pl >= 0 ? "+" : ""}
                      {usd(e.unrealized_pl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        This section reflects what Alpaca actually shows for your
        account; the modeled planner below shows what the bot would do
        next under the same wheel rules. When both are in view, the
        live legs are the truth — the planner is the road map.
      </p>
    </section>
  );
}

function Stat({
  label,
  value,
  tone
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          (tone === "neutral" || !tone) && "text-weave-800"
        )}
      >
        {value}
      </p>
    </div>
  );
}
