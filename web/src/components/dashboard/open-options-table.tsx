import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

type Row = {
  id: string;
  underlying: string;
  strategy: string;
  option_type: string | null;
  strike: number | null;
  expiration: string | null;
  contracts: number;
  net_premium_usd: number;
  status: string;
  opened_at: string;
};

// Mirror of agents/app/learning/bucket_helpers.py so the UI labels
// match the agent classification. Stays in sync via review (no
// shared codegen yet).
function strategyBucket(strategy: string): "wheel" | "income" | "hopeful" {
  const s = (strategy || "").toLowerCase();
  if (s === "wheel_csp" || s === "wheel_cc") return "wheel";
  if (
    s === "long_call" || s === "long_put" || s === "bull_call_spread"
  ) return "hopeful";
  return "income";
}

function dteFromExpiration(exp: string | null): number | null {
  if (!exp) return null;
  const d = new Date(exp.slice(0, 10) + "T16:00:00Z");
  const now = new Date();
  const ms = d.getTime() - now.getTime();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/**
 * OpenOptionsTable — every open options_positions row grouped by bucket
 * with DTE color-coding. The visual proof that the Phase D bucket
 * classification is working in the agents and the Wheel auto-execute /
 * modeled CSP paths are filling the table cleanly.
 *
 * Renders an EmptyCard when no open positions.
 */
export async function OpenOptionsTable() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data: rowsRaw } = await supabase
    .from("options_positions")
    .select(
      "id, underlying, strategy, option_type, strike, expiration, contracts, net_premium_usd, status, opened_at"
    )
    .eq("user_id", user.id)
    .eq("status", "open")
    .order("opened_at", { ascending: false });

  const rows = (rowsRaw ?? []) as Row[];

  if (rows.length === 0) {
    return (
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Open options{" "}
          <span className="text-sm text-weave-500">(0)</span>
        </h2>
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
          No open option positions. When the Wheel fires or you place a
          contract, it appears here with its bucket and DTE.
        </div>
      </section>
    );
  }

  // Group counts per bucket for the header summary.
  const counts = { wheel: 0, income: 0, hopeful: 0 } as Record<string, number>;
  for (const r of rows) counts[strategyBucket(r.strategy)] += 1;

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <h2 className="font-serif text-xl text-weave-800">
          Open options{" "}
          <span className="text-sm text-weave-500">({rows.length})</span>
        </h2>
        <div className="flex items-baseline gap-3 text-[11px] uppercase tracking-widest text-weave-500">
          <span>
            wheel <span className="text-weave-700 font-mono">{counts.wheel}</span>
          </span>
          <span>
            income <span className="text-weave-700 font-mono">{counts.income}</span>
          </span>
          <span>
            hopeful <span className="text-weave-700 font-mono">{counts.hopeful}</span>
          </span>
        </div>
      </div>
      <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[820px]">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
              <th className="px-4 py-3">Ticker</th>
              <th className="px-4 py-3">Strategy</th>
              <th className="px-4 py-3">Bucket</th>
              <th className="px-4 py-3 text-right">Contracts</th>
              <th className="px-4 py-3 text-right">Strike</th>
              <th className="px-4 py-3 text-right">DTE</th>
              <th className="px-4 py-3 text-right">Premium</th>
              <th className="px-4 py-3">Opened</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const bucket = strategyBucket(r.strategy);
              const dte = dteFromExpiration(r.expiration);
              const dteTone =
                dte === null
                  ? "text-weave-500"
                  : dte <= 7
                  ? "text-red-700"
                  : dte <= 21
                  ? "text-amber-700"
                  : "text-weave-700";
              const bucketTone =
                bucket === "hopeful"
                  ? "bg-amber-100 text-amber-800"
                  : bucket === "wheel"
                  ? "bg-treasure-100 text-treasure-800"
                  : "bg-weave-100 text-weave-700";
              return (
                <tr key={r.id} className="border-b border-weave-50 last:border-0">
                  <td className="px-4 py-3 font-mono font-medium text-weave-800">
                    {r.underlying}
                  </td>
                  <td className="px-4 py-3 text-xs text-weave-600">
                    {r.strategy.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5 font-medium",
                        bucketTone
                      )}
                    >
                      {bucket}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.contracts}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {r.strike !== null ? fmtUsd(r.strike) : "—"}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-3 text-right font-mono",
                      dteTone
                    )}
                  >
                    {dte !== null ? `${dte}d` : "—"}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-3 text-right font-mono",
                      r.net_premium_usd > 0
                        ? "text-emerald-700"
                        : r.net_premium_usd < 0
                        ? "text-red-700"
                        : "text-weave-600"
                    )}
                  >
                    {r.net_premium_usd > 0 ? "+" : ""}
                    {fmtUsd(r.net_premium_usd)}
                  </td>
                  <td className="px-4 py-3 text-xs text-weave-500">
                    {new Date(r.opened_at).toLocaleDateString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-weave-500 leading-relaxed">
        Bucket reflects how the Risk Manager and Exit Advisor classify
        each position. DTE color: <span className="text-red-700">red</span>{" "}
        ≤ 7 days, <span className="text-amber-700">amber</span> ≤ 21 days.
        Premium is positive when credit was received, negative when debit
        was paid.
      </p>
    </section>
  );
}
