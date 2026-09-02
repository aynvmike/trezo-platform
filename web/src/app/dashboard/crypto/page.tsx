import { redirect } from "next/navigation";
import { LayerHero } from "@/components/dashboard/layer-hero";
import { createClient } from "@/lib/supabase/server";
import { CryptoCards } from "@/components/widgets/crypto-card";
import { LoadError, loadResult } from "@/components/dashboard/load-error";
import { getOwnerBookKeys, bookQueryKeys, withBooks } from "@/lib/books";
import { cn } from "@/lib/utils";

import { Disclosure } from "@/components/ui/disclosure";

export const dynamic = "force-dynamic";

function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

const MODE_COLOR: Record<string, string> = {
  scalp: "bg-weave-100 text-weave-800",
  swing: "bg-treasure-200 text-treasure-800",
  dca:   "bg-amber-100 text-amber-800",
  hodl:  "bg-indigo-100 text-indigo-800"
};

export default async function CryptoPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/crypto");

  // rv:web-pages sweep: paper_positions is keyed by BOOK (0047); read
  // every book the person owns.
  const booksLoad = await getOwnerBookKeys(supabase, user.id);
  const keys = bookQueryKeys(booksLoad.data);

  const [openRes, scanRes] = await Promise.all([
    supabase
      .from("paper_positions")
      .select("*")
      .in("user_id", keys)
      .like("strategy", "crypto_%")
      .eq("status", "open")
      .order("entry_at", { ascending: false }),
    supabase
      .from("agent_messages")
      .select("*")
      .eq("agent_name", "crypto_scanner")
      .eq("kind", "signal")
      .order("created_at", { ascending: false })
      .limit(15)
  ]);

  // PAGES-03: keep "read failed" distinct from "nothing there".
  const openLoad = withBooks(booksLoad, loadResult("paper_positions", openRes, []));
  const scanLoad = loadResult("agent_messages", scanRes, []);
  const openCrypto = openLoad.data ?? [];
  const cryptoSignals = scanLoad.data ?? [];

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <LayerHero id={1} openCount={openLoad.failure ? undefined : openCrypto.length} />

      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">Live prices</h2>
        <CryptoCards symbols={["XRP", "ETH", "SOL", "BTC"]} />
      </section>

      {/* Recent crypto-bot signals */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Recent crypto signals <span className="text-sm text-weave-500">({cryptoSignals.length})</span>
        </h2>
        {scanLoad.failure ? (
          <LoadError {...scanLoad.failure} />
        ) : cryptoSignals.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No crypto signals yet. The scanner emits one when a coin&apos;s RSI,
            Bollinger width, and volume line up for a SCALP / SWING / DCA setup
            and the Trade Confidence Score clears the crypto floor (35 by default on the 0–100 scale, or the book&apos;s own threshold if lower).
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Coin</th>
                  <th className="px-4 py-3">Mode</th>
                  <th className="px-4 py-3 text-right">RSI</th>
                  <th className="px-4 py-3 text-right">BB width</th>
                  <th className="px-4 py-3 text-right">TCS</th>
                  <th className="px-4 py-3">When</th>
                </tr>
              </thead>
              <tbody>
                {cryptoSignals.map((m) => {
                  const cs = m.payload?.crypto_signal ?? {};
                  const mode = String(m.payload?.mode ?? "—");
                  return (
                    <tr key={m.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {m.payload?.ticker ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn(
                          "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                          MODE_COLOR[mode] ?? "bg-weave-50 text-weave-500"
                        )}>
                          {mode}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono">{cs.rsi ?? "—"}</td>
                      <td className="px-4 py-3 text-right font-mono">
                        {cs.bb_width_pct !== undefined ? `${cs.bb_width_pct}%` : "—"}
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

      {/* Open crypto positions */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Open crypto positions <span className="text-sm text-weave-500">({openCrypto.length})</span>
        </h2>
        {openLoad.failure ? (
          <LoadError {...openLoad.failure} />
        ) : openCrypto.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No open crypto positions.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Coin</th>
                  <th className="px-4 py-3">Mode</th>
                  <th className="px-4 py-3 text-right">Qty</th>
                  <th className="px-4 py-3 text-right">Entry</th>
                  <th className="px-4 py-3 text-right">Stop</th>
                  <th className="px-4 py-3 text-right">Target</th>
                </tr>
              </thead>
              <tbody>
                {openCrypto.map((p) => (
                  <tr key={p.id} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-3 font-mono font-medium text-weave-800">{p.ticker}</td>
                    <td className="px-4 py-3 text-xs text-weave-500">
                      {String(p.strategy ?? "").replace("crypto_", "")}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{Number(p.quantity).toFixed(4)}</td>
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

      <Disclosure title="Crypto modes & how trades run">
        <p>
          <span className="font-medium text-weave-800">Modes:</span>{" "}
          SCALP = RSI 40-68 with volume (tight 1.5% stop, 3% target) ·{" "}
          SWING = Bollinger width &gt; 2.5% in an uptrend (5% stop, 12% target; step-ladder profit lock ratchets the stop up as it climbs) ·{" "}
          DCA = RSI below 35, oversold accumulation (wider stop, per-coin target) ·{" "}
          HODL = RSI below 25, deep-value long-horizon hold (-35% catastrophe stop, no profit target; trails up to lock gains after a big run, never force-sells).
        </p>
        <p className="mt-2">
          The ISO 20022 coins Alpaca cannot trade (XLM, HBAR, ALGO, IOTA,
          QNT, XDC, XYO) run on the modeled paper engine using live prices.
          A real Coinbase/Kraken connector is scaffolded and stays off
          until API keys are added — for now every crypto trade runs on
          the paper account.
        </p>
      </Disclosure>
    </div>
  );
}
