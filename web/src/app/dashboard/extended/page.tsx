import { redirect } from "next/navigation";
import { LayerHero } from "@/components/dashboard/layer-hero";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { Disclosure } from "@/components/ui/disclosure";
import { LoadError, loadResult } from "@/components/dashboard/load-error";

export const dynamic = "force-dynamic";

const EXTENDED_WATCHLIST = [
  "CZR", "AMD", "INTC", "WMT", "AMSC",
  "NVDA", "MSFT", "AAPL", "PYPL", "DIS", "BAC", "F"
];

const SETUP_LABELS: Record<string, string> = {
  ema50_pullback: "EMA50 pullback",
  breakout_hold: "Breakout hold",
  gap_continuation: "Gap continuation",
  stair_stepper: "Stair stepper"
};

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

/** The Extended scanner sweeps mid-session — ~10 AM-3:30 PM ET,
 *  approximated as 14:00-20:30 UTC. Weekdays only. */
function inSwingWindow(): boolean {
  const now = new Date();
  const day = now.getUTCDay();
  if (day === 0 || day === 6) return false;
  const h = now.getUTCHours() + now.getUTCMinutes() / 60;
  return h >= 14 && h <= 20.5;
}

export default async function ExtendedPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/extended");

  const [openRes, closedRes, scanRes] = await Promise.all([
    supabase
      .from("paper_positions")
      .select("*")
      .eq("user_id", user.id)
      .eq("strategy", "extended")
      .eq("status", "open")
      .order("entry_at", { ascending: false }),
    supabase
      .from("paper_positions")
      .select("*")
      .eq("user_id", user.id)
      .eq("strategy", "extended")
      .neq("status", "open")
      .order("exit_at", { ascending: false })
      .limit(20),
    supabase
      .from("agent_messages")
      .select("*")
      .eq("agent_name", "extended_scanner")
      .order("created_at", { ascending: false })
      .limit(20)
  ]);

  // PAGES-03: keep "read failed" distinct from "nothing there".
  const openLoad = loadResult("paper_positions", openRes, []);
  const closedLoad = loadResult("paper_positions (closed)", closedRes, []);
  const scanLoad = loadResult("agent_messages", scanRes, []);
  const openPositions = openLoad.data ?? [];
  const closedPositions = closedLoad.data ?? [];
  const scanMessages = scanLoad.data ?? [];

  const windowOpen = inSwingWindow();
  const latestScan = scanMessages.find(
    (m) => m.kind === "info" && m.payload?.note === "Extended scan complete"
  );
  const recentSignals = scanMessages.filter((m) => m.kind === "signal");

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <LayerHero id={4} openCount={openLoad.failure ? undefined : openPositions.length} action={<Link href="/dashboard/stocks" className="text-sm text-weave-600 hover:underline">Watchlist quotes →</Link>} />

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
            ? "Inside the mid-session swing window. The Extended scanner sweeps the watchlist every 30 minutes."
            : "Outside the 10 AM–3:30 PM ET swing window. The scanner resumes automatically each weekday."}
        </p>
        {latestScan && (
          <p className="mt-2 text-xs text-weave-500">
            Last scan: {Number(latestScan.payload?.scanned ?? 0)} names checked ·{" "}
            {Number(latestScan.payload?.signals ?? 0)} signal(s) ·{" "}
            {new Date(latestScan.created_at).toLocaleString()}
          </p>
        )}
        <p className="mt-2 text-xs text-weave-500">
          On an FOMC decision day the scanner sits out until 2 PM ET — no new
          swing entries before the rate announcement.
        </p>
      </section>

      {/* Recent qualifying signals */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Recent swing signals{" "}
          <span className="text-sm text-weave-500">({recentSignals.length})</span>
        </h2>
        {scanLoad.failure ? (
          <LoadError {...scanLoad.failure} />
        ) : recentSignals.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No qualifying signals yet. A swing signal fires only when a
            watchlist name forms one of the four setups and scores TCS 70+ on the 0–100 scale.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[680px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Setup</th>
                  <th className="px-4 py-3 text-right">TCS</th>
                  <th className="px-4 py-3 text-right">Stop</th>
                  <th className="px-4 py-3 text-right">Target</th>
                  <th className="px-4 py-3">When</th>
                </tr>
              </thead>
              <tbody>
                {recentSignals.map((m) => {
                  const ext = m.payload?.extended ?? {};
                  const stopPct = Number(m.payload?.stop_pct ?? 0) * 100;
                  const targetPct = Number(m.payload?.target_pct ?? 0) * 100;
                  return (
                    <tr key={m.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {m.payload?.ticker ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-weave-700">
                        {SETUP_LABELS[String(ext.setup)] ?? ext.setup ?? "—"}
                        {ext.catalyst ? (
                          <span className="ml-2 rounded-full bg-treasure-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-treasure-700">
                            catalyst
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-medium text-weave-800">
                        {m.payload?.tcs ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-weave-500">
                        {stopPct ? stopPct.toFixed(1) + "%" : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-700">
                        {targetPct ? "+" + targetPct.toFixed(1) + "%" : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {new Date(m.created_at).toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Open swing positions */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Open swing positions{" "}
          <span className="text-sm text-weave-500">({openPositions.length})</span>
        </h2>
        {openLoad.failure ? (
          <LoadError {...openLoad.failure} />
        ) : openPositions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No open swing positions. Positions appear here after a signal is
            approved by Risk Manager — and each closes on its stop, its target,
            or a multi-day time stop (~5 trading days).
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
                  <th className="px-4 py-3">Held since</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p) => (
                  <tr key={p.id} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-3 font-mono font-medium text-weave-800">{p.ticker}</td>
                    <td className="px-4 py-3 text-right font-mono">
                      {Number(p.quantity).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{fmtUsd(p.entry_price)}</td>
                    <td className="px-4 py-3 text-right font-mono text-weave-500">
                      {fmtUsd(p.stop_price)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-weave-500">
                      {fmtUsd(p.target_price)}
                    </td>
                    <td className="px-4 py-3 text-xs text-weave-500">
                      {p.entry_at ? new Date(p.entry_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Closed swing trades */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Recent swing trades{" "}
          <span className="text-sm text-weave-500">({closedPositions.length})</span>
        </h2>
        {closedLoad.failure ? (
          <LoadError {...closedLoad.failure} />
        ) : closedPositions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No closed swing trades yet.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Exit</th>
                  <th className="px-4 py-3 text-right">P&amp;L</th>
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
                      <td
                        className={cn(
                          "px-4 py-3 text-right font-mono font-medium",
                          win ? "text-emerald-700" : "text-red-700"
                        )}
                      >
                        {win ? "+" : ""}
                        {fmtUsd(pnl)}
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

      <Disclosure title="About this layer" hint="the four setups, watchlist, how trades exit">
        <p className="font-medium text-weave-800">
          Extended watchlist ({EXTENDED_WATCHLIST.length} mid-caps):
        </p>
        <p className="mt-1 font-mono text-xs text-weave-500">
          {EXTENDED_WATCHLIST.join(" · ")}
        </p>
        <p className="mt-3">
          <span className="font-medium text-weave-800">The four swing setups:</span>{" "}
          EMA50 pullback (bounce off the rising 50-day average), breakout hold
          (a multi-week high that holds), gap continuation (an unfilled 4%+
          earnings gap), and stair stepper (a steady ladder of higher highs and
          higher lows).
        </p>
        <p className="mt-1">
          <span className="font-medium text-weave-800">How positions exit:</span>{" "}
          each swing trade carries a stop and a target, and is closed on a
          multi-day time stop after roughly five trading days — Extended trades
          are deliberately held across sessions, never force-exited intraday.
        </p>
        <p className="mt-1">
          <span className="font-medium text-weave-700">No mid-trade
          exits.</span> Once entered, a Stock Weekly position lives
          until its stop, target, or the multi-day time stop fires.
        </p>
      </Disclosure>
    </div>
  );
}
