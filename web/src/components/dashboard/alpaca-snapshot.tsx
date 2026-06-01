import { cn } from "@/lib/utils";
import {
  fetchAlpacaSnapshot,
  type AlpacaSnapshot as Snap
} from "@/lib/alpaca-snapshot";

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  });
}

/**
 * Detail panel for the Alpaca paper account — buying power, day-trade
 * count, status pill, and the open-positions table. The headline cash /
 * equity / today-P&L numbers move into the Paper page's KPI tiles when
 * Alpaca is configured, so this panel never duplicates them.
 */
export async function AlpacaSnapshot({
  snap: passedSnap
}: {
  snap?: Snap | null;
} = {}) {
  const snap: Snap | null = passedSnap ?? (await fetchAlpacaSnapshot());
  if (!snap) return null;
  if (!snap.configured) {
    return (
      <section className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-600 leading-relaxed">
        <p className="font-medium text-weave-800">Alpaca paper account — not connected</p>
        <p className="beginner-only mt-1">
          When you set <code className="text-xs">ALPACA_API_KEY</code> and{" "}
          <code className="text-xs">ALPACA_SECRET_KEY</code> on the agents
          service, this panel becomes the source of truth for cash,
          equity and positions. Until then the Trezo internal ledger
          above is the only view.
        </p>
      </section>
    );
  }
  if (!snap.account) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
        <p className="font-medium">Alpaca configured but unreachable</p>
        <p className="mt-1 leading-relaxed">
          {snap.note || "The account snapshot could not be fetched right now."}
        </p>
      </section>
    );
  }

  const a = snap.account;
  const positions = snap.positions ?? [];
  const totalUnrealized = positions.reduce(
    (s, p) => s + (p.unrealized_pl || 0),
    0
  );
  const asOf = snap.as_of ? new Date(snap.as_of).toLocaleString() : "";

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Alpaca paper account
          </h2>
          <p className="text-xs text-weave-500">
            {snap.venue?.toUpperCase()} · the cash and Today P&amp;L tiles
            above are now synced with this account · refreshed {asOf}
          </p>
        </div>
        <span
          className={cn(
            "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
            a.trading_blocked
              ? "bg-red-100 text-red-800"
              : "bg-emerald-100 text-emerald-800"
          )}
        >
          {a.status} {a.trading_blocked ? "· trading blocked" : ""}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Stat label="Buying power" value={usd(a.buying_power)} />
        <Stat
          label="Open P&L"
          value={`${totalUnrealized >= 0 ? "+" : ""}${usd(totalUnrealized)}`}
          tone={totalUnrealized >= 0 ? "good" : "bad"}
        />
        <Stat
          label="Day-trades used"
          value={`${a.daytrade_count}${a.pattern_day_trader ? " · PDT" : ""}`}
        />
      </div>

      {positions.length > 0 ? (
        <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Avg entry</th>
                <th className="px-4 py-3 text-right">Mark</th>
                <th className="px-4 py-3 text-right">Market value</th>
                <th className="px-4 py-3 text-right">Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.symbol} className="border-b border-weave-50 last:border-0">
                  <td className="px-4 py-2.5 font-mono font-medium text-weave-800">
                    {p.symbol}
                  </td>
                  <td className="px-4 py-2.5 text-weave-600 text-xs">
                    {p.side}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">{p.qty}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-weave-500">
                    {usd(p.avg_entry_price)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {usd(p.current_price)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {usd(p.market_value)}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2.5 text-right font-mono font-medium",
                      p.unrealized_pl >= 0 ? "text-emerald-700" : "text-red-700"
                    )}
                  >
                    {p.unrealized_pl >= 0 ? "+" : ""}
                    {usd(p.unrealized_pl)}
                    <span className="block text-[10px] text-weave-500 font-normal">
                      {p.unrealized_plpc >= 0 ? "+" : ""}
                      {p.unrealized_plpc.toFixed(2)}%
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-weave-500">
          No open Alpaca positions right now.
        </p>
      )}
      <p className="beginner-only text-xs text-weave-500 leading-relaxed">
        These positions and the synced cash / today-P&amp;L tiles above
        come straight from Alpaca&apos;s paper-trading API — the
        authoritative ledger. Trezo&apos;s vault balance and daily-lock
        progress remain Trezo-side concepts and continue to use the
        internal ledger.
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
