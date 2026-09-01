import { redirect } from "next/navigation";
import { LayerHero } from "@/components/dashboard/layer-hero";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { Disclosure } from "@/components/ui/disclosure";
import { WheelReconcileButton } from "@/components/dashboard/wheel-reconcile-button";
import { LoadError, loadResult } from "@/components/dashboard/load-error";

export const dynamic = "force-dynamic";

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

const STRATEGY_LABEL: Record<string, string> = {
  long_call: "Long Call",
  bull_call_spread: "Bull Call Spread",
  cash_secured_put: "Cash-Secured Put",
  bull_put_spread: "Bull Put Spread",
  iron_condor: "Iron Condor",
  wheel_csp: "Wheel — Cash-Secured Put",
  wheel_cc: "Wheel — Covered Call"
};

function prettyStrategy(s: string): string {
  return STRATEGY_LABEL[s] ?? String(s).replace(/_/g, " ");
}

const STATUS_COLOR: Record<string, string> = {
  open: "bg-weave-100 text-weave-800",
  closed_expired: "bg-emerald-100 text-emerald-800",
  closed_assigned: "bg-amber-100 text-amber-800",
  closed_manual: "bg-weave-50 text-weave-500",
  closed_profit: "bg-emerald-100 text-emerald-800"
};

type BookRow = {
  id: string;
  underlying: string;
  strategy: string;
  strike: number | null;
  expiration: string | null;
  contracts: number;
  net_premium_usd: number;
  status: string;
  realized_pnl_usd: number | null;
};

type Greeks = { delta?: number; gamma?: number; theta?: number; vega?: number };

type IdeaMessage = {
  id: string;
  created_at: string;
  payload: {
    event?: string;
    underlying?: string;
    strategy?: string;
    direction?: string;
    expiration?: string;
    contracts?: number;
    net_premium_usd?: number;
    max_loss_usd?: number | null;
    max_gain_usd?: number | null;
    modeled_iv?: number;
    greeks?: Greeks;
    notes?: string;
  };
};

function num(n: number | null | undefined, digits = 1, sign = false): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return (sign && v >= 0 ? "+" : "") + v.toFixed(digits);
}

export default async function OptionsPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/options");

  const [bookRes, ideaRes] = await Promise.all([
    supabase
      .from("options_positions")
      .select("id, underlying, strategy, strike, expiration, contracts, net_premium_usd, status, realized_pnl_usd")
      .eq("user_id", user.id)
      .order("opened_at", { ascending: false }),
    supabase
      .from("agent_messages")
      .select("id, created_at, payload")
      .eq("agent_name", "options_scanner")
      .eq("kind", "info")
      .order("created_at", { ascending: false })
      .limit(40)
  ]);

  // PAGES-03: keep "read failed" distinct from "nothing there".
  const bookLoad = loadResult<BookRow[]>("options_positions", bookRes, []);
  const ideaLoad = loadResult<IdeaMessage[]>("agent_messages", ideaRes, []);
  const allBook = bookLoad.data ?? [];
  const ideas = (ideaLoad.data ?? [])
    .filter((m) => m.payload?.event === "options_idea")
    .slice(0, 12);

  // Mike feedback 2026-05-29: 28 closed_manual reconcile rows with
  // $0 realized P&L were cluttering the lifetime book. They are not
  // trades — they are phantoms that the modeled scanner inserted
  // before Alpaca was wired, then the reconcile closed without any
  // realized outcome. Filter them out of the user-visible book and
  // the lifetime count. The rows stay in the DB (auditable) but the
  // UI now only shows REAL trades — anything with a non-zero realized
  // outcome, plus everything that's still open.
  const book = allBook.filter((p) => {
    if (p.status === "open") return true;
    const pnl = Number(p.realized_pnl_usd ?? 0);
    return Math.abs(pnl) > 0.001;
  });
  const hiddenPhantoms = allBook.length - book.length;

  const openBook = book.filter((p) => p.status === "open");
  // "Premium at work" = credit on positions that are CURRENTLY OPEN.
  // Reconciled / settled positions no longer carry working credit —
  // their realized value moves to "Realized P&L" below.
  const creditAtWork = openBook.reduce(
    (s, p) => s + Number(p.net_premium_usd ?? 0),
    0
  );
  const realized = book
    .filter((p) => p.status !== "open")
    .reduce((s, p) => s + Number(p.realized_pnl_usd ?? 0), 0);

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <LayerHero id={3} openCount={bookLoad.failure ? undefined : openBook.length} />

      <WheelReconcileButton />

      {bookLoad.failure ? (
        <LoadError {...bookLoad.failure} />
      ) : (
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Currently open" value={String(openBook.length)} />
        <StatCard
          label="Premium at work"
          value={usd(creditAtWork)}
          tone={creditAtWork > 0 ? "good" : undefined}
        />
        <StatCard
          label="Realized P&L"
          value={usd(realized)}
          tone={realized >= 0 ? "good" : "bad"}
        />
        <StatCard label="Lifetime book" value={String(book.length)} />
      </section>
      )}
      {hiddenPhantoms > 0 && (
        <p className="text-[11px] text-weave-500 leading-relaxed -mt-4">
          {hiddenPhantoms} stale reconcile row{hiddenPhantoms === 1 ? "" : "s"} hidden
          from the book (closed with $0 realized — typically modeled
          phantoms cleared during a reset). They stay in the database for
          audit; they just don&apos;t pollute the count.
        </p>
      )}

      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-1">
          Strategy ideas{" "}
          <span className="text-sm text-weave-500">({ideas.length})</span>
        </h2>
        <p className="text-sm text-weave-500 mb-3">
          Suggestions only — the Options Scanner posts these every 30 minutes.
          Each card shows how the trade is built and the net Greeks it carries.
          Nothing here is traded automatically.
        </p>
        {ideaLoad.failure ? (
          <LoadError {...ideaLoad.failure} />
        ) : ideas.length === 0 ? (
          <EmptyCard>
            No strategy ideas yet. The scanner surfaces a Long Call, Bull Call
            Spread, Cash-Secured Put, Bull Put Spread, or Iron Condor idea when
            a watchlist name lines up.
          </EmptyCard>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {ideas.map((m) => {
              const p = m.payload ?? {};
              const prem = Number(p.net_premium_usd ?? 0);
              const g: Greeks = p.greeks ?? {};
              return (
                <div
                  key={m.id}
                  className="rounded-xl border border-weave-100 bg-white p-4 space-y-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="font-mono font-medium text-weave-800">
                        {p.underlying ?? "—"}
                      </span>
                      <span className="ml-2 text-sm text-weave-600">
                        {prettyStrategy(String(p.strategy ?? ""))}
                      </span>
                    </div>
                    <span className="shrink-0 text-[10px] uppercase tracking-widest rounded-full bg-weave-50 text-weave-500 px-2 py-0.5">
                      {p.direction ?? "modeled"}
                    </span>
                  </div>

                  <div className="grid grid-cols-3 gap-2">
                    <Fig
                      label={prem >= 0 ? "Net credit" : "Net debit"}
                      value={prem >= 0 ? usd(prem) : usd(Math.abs(prem))}
                      tone={prem >= 0 ? "good" : "neutral"}
                    />
                    <Fig label="Max loss" value={usd(p.max_loss_usd)} tone="bad" />
                    <Fig
                      label="Max gain"
                      value={
                        p.max_gain_usd === null ||
                        p.max_gain_usd === undefined ||
                        Number(p.max_gain_usd) < 0
                          ? "Unlimited"
                          : usd(p.max_gain_usd)
                      }
                      tone="good"
                    />
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-weave-500 mb-1">
                      Position Greeks
                    </p>
                    <div className="grid grid-cols-4 gap-2">
                      <GreekChip sym="Δ" label="Delta" value={num(g.delta, 1, true)} />
                      <GreekChip sym="Γ" label="Gamma" value={num(g.gamma, 2, true)} />
                      <GreekChip sym="Θ" label="Theta/day" value={num(g.theta, 2, true)} />
                      <GreekChip sym="ν" label="Vega/1%" value={num(g.vega, 2, true)} />
                    </div>
                  </div>

                  {p.notes && (
                    <p className="text-xs text-weave-500 leading-relaxed">{p.notes}</p>
                  )}
                  <p className="text-[10px] text-weave-400">
                    {p.expiration ? `Expires ${p.expiration} · ` : ""}
                    posted {new Date(m.created_at).toLocaleString()}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Options book{" "}
          <span className="text-sm text-weave-500">({book.length})</span>
        </h2>
        {bookLoad.failure ? (
          <LoadError {...bookLoad.failure} />
        ) : book.length === 0 ? (
          <EmptyCard>
            No options positions yet. The Wheel (Layer 5) opens
            cash-secured puts here automatically once your paper
            account is active.
          </EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[780px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Underlying</th>
                  <th className="px-4 py-3">Strategy</th>
                  <th className="px-4 py-3 text-right">Strike</th>
                  <th className="px-4 py-3 text-right">Contracts</th>
                  <th className="px-4 py-3 text-right">Premium</th>
                  <th className="px-4 py-3">Expiration</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Realized</th>
                </tr>
              </thead>
              <tbody>
                {book.map((p) => {
                  const realizedRow = Number(p.realized_pnl_usd ?? 0);
                  return (
                    <tr key={p.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {p.underlying}
                      </td>
                      <td className="px-4 py-3 text-weave-600">
                        {prettyStrategy(p.strategy)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">{usd(p.strike)}</td>
                      <td className="px-4 py-3 text-right font-mono">{p.contracts}</td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-700">
                        {usd(p.net_premium_usd)}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {p.expiration ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                            STATUS_COLOR[p.status] ?? "bg-weave-50 text-weave-500"
                          )}
                        >
                          {p.status.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td
                        className={cn(
                          "px-4 py-3 text-right font-mono",
                          p.status === "open"
                            ? "text-weave-400"
                            : realizedRow > 0
                              ? "text-emerald-700"
                              : realizedRow < 0
                                ? "text-red-600"
                                : "text-weave-500"
                        )}
                      >
                        {p.status === "open" || p.realized_pnl_usd === null
                          ? "—"
                          : usd(realizedRow)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Disclosure title="How to read this — modeled pricing & the Greeks">
        <p>
          <span className="font-medium text-weave-800">Modeled pricing:</span>{" "}
          every premium, max-loss, max-gain and Greek is computed with a
          Black-Scholes pricer. Trezo has no live options-chain feed, so treat
          these as well-reasoned estimates, not executable quotes.
        </p>
        <p className="mt-2">
          <span className="font-medium text-weave-800">The Greeks</span> are
          shown for the whole position. Delta is its directional exposure
          (roughly how many shares it behaves like); Gamma is how fast that
          delta shifts; Theta is the dollars gained or lost to time each day;
          Vega is the dollars per one-point move in implied volatility.
        </p>
        <p className="mt-2">
          The Wheel (Layer 5) acts on its own — conservative and
          cash-secured. Directional ideas on this page are surfaced
          for you to consider; real-money options execution stays
          gated behind the go-live checklist.
        </p>
        <p className="mt-3 pt-3 border-t border-weave-100">
          <span className="font-medium text-weave-800">
            Positions out of sync with Alpaca?
          </span>{" "}
          The Options Scanner stops auto-inserting modeled CSPs once Alpaca
          is configured — but the agents service must be restarted to load
          the gate. If &quot;Currently open&quot; above doesn&apos;t match
          what Alpaca shows you, restart agents with{" "}
          <code className="font-mono text-[11px] bg-white/60 px-1 py-0.5 rounded">
            cd agents && uv run uvicorn app.main:app --port 8001
          </code>{" "}
          then click Reconcile.
        </p>
      </Disclosure>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-4">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          !tone && "text-weave-800"
        )}
      >
        {value}
      </p>
    </div>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
      {children}
    </div>
  );
}

function Fig({
  label,
  value,
  tone = "neutral"
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "neutral";
}) {
  return (
    <div className="rounded-lg border border-weave-100 bg-treasure-50/40 p-2">
      <p className="text-[10px] uppercase tracking-widest text-weave-500">{label}</p>
      <p
        className={cn(
          "mt-0.5 font-mono text-sm font-medium",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-600",
          tone === "neutral" && "text-weave-800"
        )}
      >
        {value}
      </p>
    </div>
  );
}

function GreekChip({
  sym,
  label,
  value
}: {
  sym: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-weave-100 bg-weave-50/50 p-2 text-center">
      <p className="font-serif text-sm text-treasure-600">{sym}</p>
      <p className="mt-0.5 font-mono text-sm font-medium text-weave-800">{value}</p>
      <p className="text-[9px] uppercase tracking-widest text-weave-500 mt-0.5">{label}</p>
    </div>
  );
}
