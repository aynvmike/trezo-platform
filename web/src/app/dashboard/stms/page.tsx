import { redirect } from "next/navigation";
import { LayerHero } from "@/components/dashboard/layer-hero";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { Disclosure } from "@/components/ui/disclosure";

export const dynamic = "force-dynamic";

const STMS_WATCHLIST = [
  "STAFQ", "NVIVQ", "ZSANQ", "XWEL", "ZNB",
  "JAGX", "SDIG", "GSAT", "ACHR",
  "SOUN", "RIVN", "PLTR", "BB", "AMC"
];

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

/** STMS trades 7-11 AM ET. We approximate the window as 11:00-16:00 UTC. */
function inTradingWindow(): boolean {
  const now = new Date();
  const day = now.getUTCDay();
  if (day === 0 || day === 6) return false;
  const h = now.getUTCHours() + now.getUTCMinutes() / 60;
  return h >= 11 && h <= 16;
}

export default async function StmsPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/stms");

  const [openRes, closedRes, scanRes] = await Promise.all([
    supabase
      .from("paper_positions")
      .select("*")
      .eq("user_id", user.id)
      .eq("strategy", "stms")
      .eq("status", "open")
      .order("entry_at", { ascending: false }),
    supabase
      .from("paper_positions")
      .select("*")
      .eq("user_id", user.id)
      .eq("strategy", "stms")
      .neq("status", "open")
      .order("exit_at", { ascending: false })
      .limit(20),
    supabase
      .from("agent_messages")
      .select("*")
      .eq("agent_name", "stms_scanner")
      .order("created_at", { ascending: false })
      .limit(20)
  ]);

  const openPositions = openRes.data ?? [];
  const closedPositions = closedRes.data ?? [];
  const scanMessages = scanRes.data ?? [];

  const windowOpen = inTradingWindow();
  const latestScan = scanMessages.find(
    (m) => m.kind === "info" && m.payload?.note === "STMS scan complete"
  );
  const recentSignals = scanMessages.filter((m) => m.kind === "signal");

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <LayerHero id={2} openCount={openPositions.length} action={<Link href="/dashboard/stocks" className="text-sm text-weave-600 hover:underline">Watchlist quotes →</Link>} />

      {/* Scanner status */}
      <section
        className={cn(
          "rounded-xl border p-5",
          windowOpen ? "border-emerald-200 bg-emerald-50" : "border-weave-100 bg-white"
        )}
      >
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              windowOpen ? "bg-emerald-500 animate-pulse" : "bg-weave-300"
            )}
          />
          <h2 className="font-serif text-xl text-weave-800">
            Scanner {windowOpen ? "active" : "idle"}
          </h2>
        </div>
        <p className="mt-2 text-sm text-weave-600 leading-relaxed">
          {windowOpen
            ? "Inside the 7–11 AM ET window. The STMS scanner is sweeping the watchlist every 90 seconds."
            : "Outside the 7–11 AM ET trading window. The scanner resumes automatically each weekday morning."}
        </p>
        {latestScan && (
          <p className="mt-2 text-xs text-weave-500">
            Last scan: {Number(latestScan.payload?.tickers_scanned ?? 0)} tickers checked ·{" "}
            {Number(latestScan.payload?.candidates_found ?? 0)} candidate(s) ·{" "}
            {new Date(latestScan.created_at).toLocaleString()}
          </p>
        )}
      </section>

      {/* Recent qualifying signals */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Recent STMS signals <span className="text-sm text-weave-500">({recentSignals.length})</span>
        </h2>
        {recentSignals.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No qualifying signals yet. A signal fires only when a watchlist
            ticker clears every filter — price, +10% move, 5× volume — AND scores
            TCS 750+. That&apos;s a deliberately high bar.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3 text-right">Price</th>
                  <th className="px-4 py-3 text-right">Day move</th>
                  <th className="px-4 py-3 text-right">Rel. vol</th>
                  <th className="px-4 py-3 text-right">TCS</th>
                  <th className="px-4 py-3">When</th>
                </tr>
              </thead>
              <tbody>
                {recentSignals.map((m) => {
                  const f = m.payload?.stms_filters ?? {};
                  return (
                    <tr key={m.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {m.payload?.ticker ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">{fmtUsd(f.price)}</td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-700">
                        +{Number(f.daily_move_pct ?? 0).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {Number(f.relative_volume ?? 0).toFixed(1)}×
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-medium text-weave-800">
                        {m.payload?.tcs ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {new Date(m.created_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Open STMS positions */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Open STMS positions <span className="text-sm text-weave-500">({openPositions.length})</span>
        </h2>
        {openPositions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No open STMS positions. Positions appear here after a signal is
            approved by Risk Manager — and all close automatically by 11 AM ET.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3 text-right">Qty</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Stop</th>
                  <th className="px-4 py-3 text-right">Target</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p) => (
                  <tr key={p.id} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-3 font-mono font-medium text-weave-800">{p.ticker}</td>
                    <td className="px-4 py-3 text-right font-mono">{Number(p.quantity).toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{fmtUsd(p.entry_price)}</td>
                    <td className="px-4 py-3 text-right font-mono text-weave-500">{fmtUsd(p.stop_price)}</td>
                    <td className="px-4 py-3 text-right font-mono text-weave-500">{fmtUsd(p.target_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Closed STMS trades */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Recent STMS trades <span className="text-sm text-weave-500">({closedPositions.length})</span>
        </h2>
        {closedPositions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No closed STMS trades yet.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Exit</th>
                  <th className="px-4 py-3 text-right">P&L</th>
                  <th className="px-4 py-3">Closed by</th>
                </tr>
              </thead>
              <tbody>
                {closedPositions.map((p) => {
                  const pnl = Number(p.realized_pnl_usd ?? 0);
                  const win = pnl >= 0;
                  return (
                    <tr key={p.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">{p.ticker}</td>
                      <td className="px-4 py-3 text-right font-mono">{fmtUsd(p.entry_price)}</td>
                      <td className="px-4 py-3 text-right font-mono">{fmtUsd(p.exit_price)}</td>
                      <td className={cn(
                        "px-4 py-3 text-right font-mono font-medium",
                        win ? "text-emerald-700" : "text-red-700"
                      )}>
                        {win ? "+" : ""}{fmtUsd(pnl)}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {String(p.status).replace("closed_", "")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Disclosure title="About this layer" hint="watchlist & live filters">
        <p className="font-medium text-weave-800">A dynamic watchlist</p>
        <p className="mt-1">
          STMS is built to trade stocks <em>in motion</em>, so the watchlist is
          no longer fixed. Each morning the scanner pulls the session&apos;s top
          gainers in the $1–$20 range and hunts there. If the movers feed is
          unavailable it falls back to a seed list of {STMS_WATCHLIST.length}{" "}
          small-caps known for morning volatility:
        </p>
        <p className="mt-1 font-mono text-xs text-weave-500">{STMS_WATCHLIST.join(" · ")}</p>
        <p className="mt-3">
          <span className="font-medium text-weave-800">Filters live:</span>{" "}
          price $1–$20, daily move +10%, relative volume 5×, small float
          (under 20M shares), a recent news catalyst, a continuation chart
          setup, and a TCS floor.
        </p>
        <p className="mt-3 text-xs text-weave-500 leading-relaxed">
          <span className="font-medium text-weave-700">The TCS floor follows your Bot Tuning setting.</span>{" "}
          Drop it in Bot Tuning and STMS fires at that lower bar
          across the same filters.
        </p>
      </Disclosure>
    </div>
  );
}
