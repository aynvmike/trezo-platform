import { fetchPremiumQuality } from "@/lib/premium-quality";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  RICH: "text-emerald-600",
  FAIR: "text-weave-600",
  CHEAP: "text-red-600",
  UNKNOWN: "text-weave-400",
};

export async function PremiumQualityCard() {
  const q = await fetchPremiumQuality(14);

  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-serif text-xl text-weave-800">
          Was the premium worth selling?
        </h2>
        <p className="max-w-2xl text-sm leading-relaxed text-weave-500">
          Selling a put or a call is selling insurance against movement. The
          price you receive contains a forecast of how far the stock will move.
          If it then moves <em>less</em> than that forecast, you keep the
          difference — so the only question that matters is whether the forecast
          was generous. <strong>RICH</strong> means the option priced more
          movement than the stock has been delivering and you were overpaid.{" "}
          <strong>CHEAP</strong> means you were underpaid for real risk.
        </p>
      </div>

      {q === null ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-weave-50/40 p-5 text-sm text-weave-500">
          Could not reach the agents service to load premium verdicts.
        </div>
      ) : q.total === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-weave-50/40 p-5 text-sm leading-relaxed text-weave-500">
          No verdicts recorded yet. One is written each time the wheel refines a
          cash-secured put against a live Alpaca quote — that is the only moment
          both the real premium and the stock&apos;s realised volatility are
          known at once.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            {(["RICH", "FAIR", "CHEAP", "UNKNOWN"] as const).map((v) => (
              <div
                key={v}
                className="rounded-xl border border-weave-100 bg-white px-4 py-3"
              >
                <div className={cn("text-lg font-medium", TONE[v])}>
                  {q.counts[v] ?? 0}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-weave-500">
                  {v}
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-weave-100 text-left text-[11px] uppercase tracking-widest text-weave-500">
                  <th className="px-4 py-3">When</th>
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Verdict</th>
                  <th className="px-4 py-3 text-right">Priced</th>
                  <th className="px-4 py-3 text-right">Actual</th>
                </tr>
              </thead>
              <tbody>
                {q.recent.slice(0, 12).map((r, i) => (
                  <tr key={`${r.ts}-${i}`} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-3 text-xs text-weave-500">
                      {r.ts.slice(0, 16).replace("T", " ")}
                    </td>
                    <td className="px-4 py-3 font-mono font-medium text-weave-800">
                      {r.ticker}
                    </td>
                    <td className={cn("px-4 py-3 font-medium", TONE[r.verdict])}>
                      {r.verdict}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {r.impliedVol != null ? `${(r.impliedVol * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {r.realizedVol != null ? `${(r.realizedVol * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs leading-relaxed text-weave-400">
            These verdicts change nothing today — they are recorded so we can
            find out whether CHEAP trades actually performed worse than RICH
            ones before any rule is altered on the strength of a theory.
          </p>
        </>
      )}
    </section>
  );
}
