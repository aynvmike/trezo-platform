import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { createClient } from "@/lib/supabase/server";
import { addChild, saveChild, deleteChild } from "./_actions";
import { getQuotes } from "@/lib/services/finnhub";
import { KindripProjection } from "./_kindrip-projection";
import { familyAccounts } from "@/lib/tax-strategy";
import { cn } from "@/lib/utils";

import { Disclosure } from "@/components/ui/disclosure";
import { PaymentInstructionsLedger } from "@/components/dashboard/payment-instructions-ledger";

export const dynamic = "force-dynamic";

const CURRENT_YEAR = new Date().getFullYear();

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "$0.00";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

type KChild = {
  id: string;
  child_name: string;
  birth_year: number | null;
  contribution_mode: string;
  contribution_value: number;
  contribution_cadence: string;
  contribution_enabled: boolean;
  allocation_mode: string;
  alloc_schd: number;
  alloc_vti: number;
  alloc_bnd: number;
  alloc_cash: number;
  cash_balance_usd: number;
  total_contributed_usd: number;
  federal_seed_applied: boolean;
};
type KHolding = {
  id: string;
  child_id: string;
  symbol: string;
  shares: number;
  cost_basis_usd: number;
};
type KTxn = {
  id: string;
  child_id: string;
  kind: string;
  amount_usd: number;
  explanation: string;
  created_at: string;
};

const INPUT =
  "rounded-md border border-weave-200 bg-white px-3 py-2 text-sm";

export default async function KindripPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/kindrip");

  const { data: childRows } = await supabase
    .from("kindrip_children")
    .select("*")
    .eq("user_id", user.id)
    .order("created_at", { ascending: true });
  const kids = (childRows ?? []) as KChild[];
  const ids = kids.length
    ? kids.map((k) => k.id)
    : ["00000000-0000-0000-0000-000000000000"];

  const [holdingsRes, txnRes] = await Promise.all([
    supabase.from("kindrip_holdings").select("*").in("child_id", ids),
    supabase
      .from("kindrip_transactions")
      .select("*")
      .in("child_id", ids)
      .order("created_at", { ascending: false })
      .limit(120)
  ]);
  const holdings = (holdingsRes.data ?? []) as KHolding[];
  const txns = (txnRes.data ?? []) as KTxn[];

  // QW5 — value child holdings at live ETF prices. Falls back to cost
  // basis per holding when a quote is unavailable (e.g. outside RTH).
  const etfQuotes = await getQuotes(["SCHD", "VTI", "BND"]);
  const priceMap: Record<string, number> = {};
  for (const q of etfQuotes) {
    if (q.current > 0) priceMap[q.symbol] = q.current;
  }

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-5xl">
      <PageHeader
        eyebrow="Layer 7 — KINDRIP"
        title="KINDRIP — generational wealth"
        subtitle="Scheduled contributions to a child's Future Index Account, auto-invested on an age-based glide path."
        explainer="The innermost ring. KINDRIP routes a contribution you set — fixed or a percentage, weekly or monthly — into a child's account that auto-invests into a steady index mix. Every deposit carries a plain explanation the child can grow up reading."
      />

      <Disclosure title="The Future Index Account">
        <div className="space-y-2">
        <p>
          The recommended home for a KINDRIP child is a Future Index Account —
          the federal child account established under the One Big Beautiful
          Bill (P.L. 119-21). A few facts worth knowing:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li>
            The government adds a one-time{" "}
            <span className="font-medium text-weave-800">$1,000</span> starter
            contribution per eligible child.
          </li>
          <li>
            Up to{" "}
            <span className="font-medium text-weave-800">$5,000 a year</span>{" "}
            can be contributed.
          </li>
          <li>
            The account cannot be funded before{" "}
            <span className="font-medium text-weave-800">July 4, 2026</span> —
            KINDRIP holds the $1,000 seed until then.
          </li>
          <li>
            Funds invest in US stock-index funds and stay invested until the
            child turns 18.
          </li>
        </ul>
        <p>
          When a contribution moves into a child&apos;s account, that money
          leaves your taxable trading balance and grows tax-advantaged here.
          Your{" "}
          <a href="/dashboard/tax" className="underline text-weave-700">
            Tax page
          </a>{" "}
          tracks the running total and explains what it means.
        </p>
        <p className="text-xs text-weave-500">
          General information, not tax or legal advice. KINDRIP here is modeled
          (paper) — opening a real account is a step you take with a broker.
        </p>
        </div>
      </Disclosure>

      {kids.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
          No children added yet. Add your first below to start a KINDRIP account.
        </div>
      ) : (
        kids.map((child) =>
          childSection(
            child,
            holdings.filter((h) => h.child_id === child.id),
            txns.filter((t) => t.child_id === child.id),
            priceMap
          )
        )
      )}

      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          {kids.length ? "Add another child" : "Add a child"}
        </h2>
        <form
          action={addChild}
          className="rounded-xl border border-weave-100 bg-white p-5 flex flex-wrap items-end gap-4"
        >
          <div className="space-y-1">
            <label htmlFor="child_name" className="block text-sm font-medium text-weave-700">
              Child&apos;s name
            </label>
            <input
              id="child_name"
              name="child_name"
              type="text"
              required
              maxLength={60}
              className={`${INPUT} w-56`}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="birth_year" className="block text-sm font-medium text-weave-700">
              Birth year
            </label>
            <input
              id="birth_year"
              name="birth_year"
              type="number"
              min={2008}
              max={CURRENT_YEAR}
              placeholder={String(CURRENT_YEAR)}
              className={`${INPUT} w-32`}
            />
          </div>
          <button
            type="submit"
            className="rounded-md bg-weave-600 px-4 py-2 text-sm font-medium text-treasure-50 hover:bg-weave-700"
          >
            Add child
          </button>
        </form>
        <p className="mt-2 text-xs text-weave-500">
          Birth year drives the Auto allocation — younger children lean toward growth.
        </p>
      </section>

      {/* ISO 20022 payment instructions ledger — every KINDRIP
          contribution writes a draft pain.001 here so the audit trail
          builds up before real banking goes live. */}
      <PaymentInstructionsLedger />

      {/* Accounts for a child's wealth — educational reference */}
      <section className="space-y-2">
        <div>
          <h2 className="font-serif text-xl text-weave-800">
            Accounts for a child&apos;s wealth
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-weave-500 leading-relaxed">
            KINDRIP runs inside a Future Index Account — but that is not the
            only place to build a child&apos;s future. Here are the account
            types worth knowing, each with a worked example. General
            information, not tax or financial advice.
          </p>
        </div>
        {familyAccounts().map((a) => (
          <Disclosure key={a.id} title={a.name}>
            <p className="text-weave-600 leading-relaxed">{a.what}</p>
            <p className="mt-2 text-treasure-700 leading-relaxed">{a.why}</p>
            <ul className="mt-3 space-y-1">
              {a.facts.map((f, i) => (
                <li
                  key={i}
                  className="flex gap-2 text-xs text-weave-500 leading-relaxed"
                >
                  <span className="text-treasure-500">•</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 rounded-lg border border-treasure-100 bg-treasure-50/60 px-3 py-2 text-xs text-weave-600 leading-relaxed">
              {a.example}
            </p>
          </Disclosure>
        ))}
      </section>
    </div>
  );
}

function childSection(
  child: KChild,
  childHoldings: KHolding[],
  childTxns: KTxn[],
  priceMap: Record<string, number>
) {
  const age =
    child.birth_year ? Math.max(0, CURRENT_YEAR - Number(child.birth_year)) : null;
  const cost = childHoldings.reduce(
    (s, h) => s + Number(h.cost_basis_usd || 0),
    0
  );
  const marketValue = childHoldings.reduce((s, h) => {
    const px = Number(priceMap[h.symbol] ?? 0);
    return s + (px > 0 ? Number(h.shares) * px : Number(h.cost_basis_usd || 0));
  }, 0);
  const cash = Number(child.cash_balance_usd || 0);
  const anyPriced = childHoldings.some(
    (h) => Number(priceMap[h.symbol] ?? 0) > 0
  );

  // Quarterly report (#124): contributions into this child this quarter.
  const now = new Date();
  const qNum = Math.floor(now.getMonth() / 3) + 1;
  const qStart = new Date(now.getFullYear(), (qNum - 1) * 3, 1);
  const quarterLabel = `Q${qNum} ${now.getFullYear()}`;
  const quarterTxns = childTxns.filter((t) => {
    if (t.kind !== "contribution" && t.kind !== "federal_seed") return false;
    const d = new Date(t.created_at);
    return !isNaN(d.getTime()) && d >= qStart;
  });
  const quarterIn = quarterTxns.reduce(
    (sum, t) => sum + Number(t.amount_usd || 0),
    0
  );
  const accountValue = marketValue + cash;
  const cadenceMult = child.contribution_cadence === "weekly" ? 52 / 12 : 1;
  const defaultMonthly =
    child.contribution_mode === "fixed"
      ? Math.round(Number(child.contribution_value || 0) * cadenceMult)
      : 100;
  const quarterNote =
    quarterIn > 0
      ? `${usd(quarterIn)} has gone into ${child.child_name}'s account so ` +
        `far this quarter, across ${quarterTxns.length} deposit` +
        `${quarterTxns.length === 1 ? "" : "s"}. The account is now worth ` +
        `${usd(accountValue)}.`
      : `No deposits yet this quarter. The next scheduled contribution ` +
        `will appear here; the account currently holds ${usd(accountValue)}.`;

  return (
    <section
      key={child.id}
      className="rounded-xl border border-weave-100 bg-white p-5 space-y-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl text-weave-800">{child.child_name}</h2>
          <p className="text-sm text-weave-500">
            {age !== null ? `Age ${age}` : "Age not set"} ·{" "}
            {child.federal_seed_applied
              ? "Federal $1,000 seed applied"
              : "Federal $1,000 seed unlocks July 4, 2026"}
          </p>
        </div>
        <form action={deleteChild}>
          <input type="hidden" name="child_id" value={child.id} />
          <button type="submit" className="text-xs text-weave-400 hover:text-red-600">
            Remove
          </button>
        </form>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Account value" value={usd(marketValue + cash)} />
        <Stat label="Invested (cost)" value={usd(cost)} />
        <Stat label="Cash" value={usd(cash)} />
        <Stat label="Total contributed" value={usd(child.total_contributed_usd)} />
      </div>

      {/* This quarter (#124) */}
      <div className="rounded-lg border border-treasure-100 bg-treasure-50/50 p-4">
        <p className="text-[11px] uppercase tracking-widest text-treasure-600">
          This quarter — {quarterLabel}
        </p>
        <p className="mt-1.5 text-sm text-weave-600 leading-relaxed">
          {quarterNote}
        </p>
      </div>

      <KindripProjection
        childName={child.child_name}
        currentValue={accountValue}
        currentAge={age}
        defaultMonthly={defaultMonthly}
      />

      {childHoldings.length > 0 && (
        <div className="rounded-lg border border-weave-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-3 py-2">Fund</th>
                <th className="px-3 py-2 text-right">Shares</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2 text-right">Value</th>
                <th className="px-3 py-2 text-right">Gain</th>
              </tr>
            </thead>
            <tbody>
              {childHoldings.map((h) => {
                const px = Number(priceMap[h.symbol] ?? 0);
                const hCost = Number(h.cost_basis_usd || 0);
                const value = px > 0 ? Number(h.shares) * px : hCost;
                const gain = value - hCost;
                return (
                  <tr key={h.id} className="border-b border-weave-50 last:border-0">
                    <td className="px-3 py-2 font-mono text-weave-800">{h.symbol}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {Number(h.shares).toFixed(4)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-weave-500">
                      {usd(hCost)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-weave-800">
                      {usd(value)}
                    </td>
                    <td className={cn(
                      "px-3 py-2 text-right font-mono",
                      gain >= 0 ? "text-emerald-700" : "text-red-700"
                    )}>
                      {gain >= 0 ? "+" : ""}{usd(gain)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!anyPriced && (
            <p className="px-3 py-2 text-[11px] text-weave-400 border-t border-weave-50">
              Live prices are unavailable right now — values shown at cost.
            </p>
          )}
        </div>
      )}

      <form action={saveChild} className="space-y-4 border-t border-weave-50 pt-4">
        <input type="hidden" name="child_id" value={child.id} />
        <div className="grid sm:grid-cols-2 gap-5">
          <div className="space-y-2">
            <p className="text-sm font-medium text-weave-700">Contribution</p>
            <div className="flex flex-wrap gap-2">
              <select
                name="contribution_mode"
                defaultValue={child.contribution_mode}
                className={INPUT}
              >
                <option value="fixed">Fixed $</option>
                <option value="percent">% of cash</option>
              </select>
              <input
                name="contribution_value"
                type="number"
                min={0}
                step="0.01"
                defaultValue={Number(child.contribution_value)}
                className={`${INPUT} w-28`}
              />
              <select
                name="contribution_cadence"
                defaultValue={child.contribution_cadence}
                className={INPUT}
              >
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm text-weave-600">
              <input
                type="checkbox"
                name="contribution_enabled"
                defaultChecked={child.contribution_enabled}
                className="accent-weave-600"
              />
              Contributions on
            </label>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium text-weave-700">Allocation</p>
            <select
              name="allocation_mode"
              defaultValue={child.allocation_mode}
              className={`${INPUT} w-full`}
            >
              <option value="auto">Auto — the AI picks by age</option>
              <option value="custom">Custom — set it yourself</option>
            </select>
            <div className="grid grid-cols-4 gap-2">
              <Weight name="alloc_schd" label="SCHD" value={child.alloc_schd} />
              <Weight name="alloc_vti" label="VTI" value={child.alloc_vti} />
              <Weight name="alloc_bnd" label="BND" value={child.alloc_bnd} />
              <Weight name="alloc_cash" label="Cash" value={child.alloc_cash} />
            </div>
            <p className="text-xs text-weave-500">
              Custom weights apply only when allocation is set to Custom.
            </p>
          </div>
        </div>
        <div className="flex justify-end">
          <button
            type="submit"
            className="rounded-md bg-weave-600 px-4 py-2 text-sm font-medium text-treasure-50 hover:bg-weave-700"
          >
            Save settings
          </button>
        </div>
      </form>

      <div className="border-t border-weave-50 pt-4">
        <p className="text-sm font-medium text-weave-700 mb-2">Recent deposits</p>
        {childTxns.length === 0 ? (
          <p className="text-sm text-weave-500">
            No deposits yet. The KINDRIP agent runs your schedule, and each
            entry — with its plain explanation — will appear here.
          </p>
        ) : (
          <ul className="space-y-2">
            {childTxns.slice(0, 8).map((t) => (
              <li key={t.id} className="text-sm text-weave-600 leading-relaxed">
                <span className="font-mono text-weave-800">{usd(t.amount_usd)}</span>
                {" — "}
                {t.explanation}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-weave-100 bg-treasure-50/50 p-3">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">{label}</p>
      <p className="mt-1 font-mono text-base font-medium text-weave-800">{value}</p>
    </div>
  );
}

function Weight({
  name,
  label,
  value
}: {
  name: string;
  label: string;
  value: number;
}) {
  return (
    <div className="space-y-1">
      <label
        htmlFor={name}
        className="block text-[11px] uppercase tracking-widest text-weave-500"
      >
        {label}
      </label>
      <input
        id={name}
        name={name}
        type="number"
        min={0}
        max={100}
        defaultValue={Math.round(Number(value) * 100)}
        className="w-full rounded-md border border-weave-200 bg-white px-2 py-1.5 text-sm"
      />
    </div>
  );
}
