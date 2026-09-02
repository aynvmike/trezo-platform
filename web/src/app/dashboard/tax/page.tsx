import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import {
  summarizeGains,
  detectWashSales,
  estimateTax,
  quarterlyEstimates,
  holdingTerm,
  TAX_YEAR,
  type ClosedPosition,
  type FilingStatus
} from "@/lib/tax";
import { TaxStrategySection } from "./_tax-strategy-section";
import { LoadErrors, loadResult, failuresOf } from "@/components/dashboard/load-error";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";

export const dynamic = "force-dynamic";

function usd(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export default async function TaxPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/tax");

  // rv:web-pages sweep: the closed book is keyed by BOOK (0047). A tax
  // estimate over one of three books is the wrong number; read them all.
  const booksLoad = await getOwnerBookKeys(supabase, user.id);
  const keys = bookQueryKeys(booksLoad.data);

  const [posRes, profRes] = await Promise.all([
    supabase
      .from("paper_positions")
      .select("id, ticker, side, quantity, entry_price, entry_at, exit_price, exit_at, realized_pnl_usd, status")
      .in("user_id", keys)
      .neq("status", "open")
      .order("exit_at", { ascending: false }),
    supabase
      .from("profiles")
      .select(
        "tax_filing_status, annual_income_usd, state_tax_rate_pct, employer_match_pct, employer_match_cap_pct, retirement_contribution_pct, withholding_set_aside_pct"
      )
      .eq("user_id", user.id)
      .maybeSingle()
  ]);

  // PAGES-03: this page used to show "$0 owed" when the positions query
  // failed. Every input to the estimate is now checked; if any of them
  // failed the estimate is not computed at all (see the early return).
  const posLoad = loadResult<ClosedPosition[]>("paper_positions", posRes, []);
  const positions = posLoad.data ?? [];

  // #122: closed options positions feed the tax math too. Each is
  // mapped to the closed-position shape the tax engine expects.
  const optLoad = loadResult(
    "options_positions",
    await supabase
      .from("options_positions")
      .select("id, underlying, contracts, realized_pnl_usd, status, created_at, closed_at")
      .in("user_id", keys)
      .neq("status", "open")
      .not("realized_pnl_usd", "is", null),
    []
  );
  const optRows = optLoad.data ?? [];
  const optionPositions: ClosedPosition[] = optRows.map((opt) => ({
    id: opt.id as string,
    ticker: `${opt.underlying} (option)`,
    side: "option",
    quantity: Number(opt.contracts ?? 1),
    entry_price: 0,
    entry_at: (opt.created_at as string) ?? new Date().toISOString(),
    exit_price: 0,
    exit_at: (opt.closed_at as string) ?? null,
    realized_pnl_usd: Number(opt.realized_pnl_usd ?? 0),
    status: opt.status as string
  }));
  // The tax estimate counts stock + options; the wash-sale scan and
  // the price-based ledger below stay stock-only (options have no
  // comparable per-share entry/exit price).
  const allClosed: ClosedPosition[] = [...positions, ...optionPositions];
  // A missing profile row is a legitimate "use defaults"; a failed read is not.
  const profLoad = loadResult("profiles", profRes);
  const profile = profLoad.data ?? {
    tax_filing_status: "single",
    annual_income_usd: 0,
    state_tax_rate_pct: 0,
    employer_match_pct: 0,
    employer_match_cap_pct: 0,
    retirement_contribution_pct: 0,
    withholding_set_aside_pct: 25
  };

  const filingStatus = (profile.tax_filing_status ?? "single") as FilingStatus;
  const annualIncome = Number(profile.annual_income_usd ?? 0);
  const stateRate = Number(profile.state_tax_rate_pct ?? 0);
  const employerMatchPct = Number(profile.employer_match_pct ?? 0);
  const employerMatchCapPct = Number(profile.employer_match_cap_pct ?? 0);
  const retirementContributionPct = Number(
    profile.retirement_contribution_pct ?? 0
  );
  const withholdingPct = Number(profile.withholding_set_aside_pct ?? 25);

  // KINDRIP child-account contributions — feed the Tax Strategy section.
  const kidsLoad = loadResult(
    "kindrip_children",
    await supabase
      .from("kindrip_children")
      .select("id, total_contributed_usd")
      .eq("user_id", user.id),
    []
  );
  const kChildren = kidsLoad.data ?? [];
  const kidIds = kChildren.map((c) => c.id as string);
  let contributedYtd = 0;
  let kTxnFailure = null as ReturnType<typeof loadResult>["failure"];
  if (kidIds.length > 0) {
    const yearStart = `${new Date().getFullYear()}-01-01`;
    const kTxnLoad = loadResult(
      "kindrip_transactions",
      await supabase
        .from("kindrip_transactions")
        .select("amount_usd")
        .in("child_id", kidIds)
        .in("kind", ["contribution", "federal_seed"])
        .gte("created_at", yearStart),
      []
    );
    kTxnFailure = kTxnLoad.failure;
    contributedYtd = (kTxnLoad.data ?? []).reduce(
      (sum, t) => sum + Number(t.amount_usd || 0),
      0
    );
  }
  // Fatal for the estimate: anything that feeds gains or the bracket.
  const estimateFailures = failuresOf(booksLoad, posLoad, optLoad, profLoad);
  // Non-fatal: only the Tax Strategy child-account panel depends on these.
  const sideFailures = [
    ...failuresOf(kidsLoad),
    ...(kTxnFailure ? [kTxnFailure] : [])
  ];
  const childAccounts = {
    childCount: kChildren.length,
    contributedYtd,
    totalContributed: kChildren.reduce(
      (sum, c) => sum + Number(c.total_contributed_usd || 0),
      0
    )
  };

  const pageHeader = (
    <PageHeader
      eyebrow="Tax Optimizer"
      title="Tax position"
      subtitle="Real-time tax-impact tracker — set-aside estimate, harvest opportunities, account-type explanations."
      explainer="A running estimate of what this year's realized trading gains could cost you, so there are no April surprises. Built from every closed paper position."
      action={
        <a href="/api/tax/export" className="text-sm rounded-md border border-weave-300 px-4 py-2 text-weave-700 hover:bg-weave-50">
          Export Schedule D CSV
        </a>
      }
    />
  );

  if (estimateFailures.length > 0) {
    // PAGES-03: no estimate at all rather than a confident "$0 owed".
    return (
      <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
        {pageHeader}
        <LoadErrors failures={[...estimateFailures, ...sideFailures]} />
        <p className="text-sm text-weave-500 leading-relaxed">
          The tax estimate needs every closed position and your profile to
          be readable. Nothing has been computed for this page load.
        </p>
      </div>
    );
  }

  const gains = summarizeGains(allClosed);
  const washSales = detectWashSales(positions);
  const estimate = estimateTax(gains, {
    annualIncome,
    filingStatus,
    stateTaxRatePct: stateRate
  });
  const quarters = quarterlyEstimates(allClosed, estimate.effectiveRatePct);

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      {pageHeader}

      <LoadErrors failures={sideFailures} />

      {/* Disclaimer — prominent, per Trezo brand + Nova's standards */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 leading-relaxed">
        <span className="font-medium">This is an estimate, not tax advice.</span>{" "}
        Based on the {TAX_YEAR} federal tax tables.{" "}
        Trezo is not a tax advisor or accountant. Brackets are approximate and
        change yearly. Use these numbers to plan and to hand to a CPA — not as a
        filed return. Wash-sale flags below are a simplified scan, not a legal
        determination.
      </div>

      {/* KPI tiles */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPI label="Realized YTD" value={usd(gains.totalRealized)} tone={gains.totalRealized >= 0 ? "good" : "bad"} />
        <KPI label="Short-term" value={usd(gains.shortTermGain)} />
        <KPI label="Long-term" value={usd(gains.longTermGain)} />
        <KPI label="Est. tax owed" value={usd(estimate.combinedTotal)} tone="treasure" />
      </section>

      {/* Estimate breakdown */}
      <section className="rounded-xl border border-weave-100 bg-white p-5">
        <h2 className="font-serif text-xl text-weave-800 mb-3">Estimated tax breakdown</h2>
        {annualIncome === 0 && (
          <p className="mb-3 text-sm text-amber-700">
            Set your annual income and state tax rate in{" "}
            <Link href="/dashboard/settings/profile" className="underline">Profile settings</Link>{" "}
            for a sharper estimate — short-term gains stack on top of your income.
          </p>
        )}
        <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <Row label="Filing status" value={filingStatus.replace(/_/g, " ")} />
          <Row label="Annual income (entered)" value={usd(annualIncome)} />
          <Row label="Federal — on short-term gains" value={usd(estimate.federalOnShortTerm)} />
          <Row label="Federal — on long-term gains" value={usd(estimate.federalOnLongTerm)} />
          <Row label="Federal total" value={usd(estimate.federalTotal)} strong />
          <Row label={`State (${stateRate}%)`} value={usd(estimate.stateTotal)} />
          <Row label="Combined estimated tax" value={usd(estimate.combinedTotal)} strong />
          <Row label="Effective rate on gains" value={`${estimate.effectiveRatePct.toFixed(1)}%`} />
        </dl>
        {optionPositions.length > 0 && (
          <p className="mt-3 text-xs text-weave-500">
            Includes realized P&amp;L from {optionPositions.length} closed
            options position{optionPositions.length === 1 ? "" : "s"}. The
            trades ledger below lists stock positions only.
          </p>
        )}
      </section>

      {/* Quarterly estimates */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">Quarterly estimated payments</h2>
        <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[480px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                <th className="px-4 py-3">Quarter</th>
                <th className="px-4 py-3">Due</th>
                <th className="px-4 py-3 text-right">Realized gain</th>
                <th className="px-4 py-3 text-right">Est. payment</th>
              </tr>
            </thead>
            <tbody>
              {quarters.map((q) => (
                <tr key={q.quarter} className="border-b border-weave-50 last:border-0">
                  <td className="px-4 py-3 font-medium text-weave-800">{q.quarter}</td>
                  <td className="px-4 py-3 text-weave-500">{q.dueDate}</td>
                  <td className={cn(
                    "px-4 py-3 text-right font-mono",
                    q.realizedGain >= 0 ? "text-emerald-700" : "text-red-700"
                  )}>
                    {usd(q.realizedGain)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-weave-800">
                    {usd(q.estimatedTax)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Wash sales */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Wash-sale flags <span className="text-sm text-weave-500">({washSales.length})</span>
        </h2>
        {washSales.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No potential wash sales detected. A wash sale is flagged when a
            losing position&apos;s ticker was re-bought within 30 days.
          </div>
        ) : (
          <div className="rounded-xl border border-amber-200 bg-amber-50 overflow-hidden">
            <ul className="divide-y divide-amber-100">
              {washSales.map((w, i) => (
                <li key={i} className="px-4 py-3 text-sm">
                  <span className="font-mono font-medium text-weave-800">{w.ticker}</span>
                  {" — "}
                  loss of <span className="font-medium text-red-700">{usd(w.lossAmount)}</span>
                  {" "}re-entered within{" "}
                  <span className="font-medium">{w.daysApart} days</span>.
                  The loss may be disallowed — confirm with a CPA.
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Closed trades ledger */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Realized trades ledger <span className="text-sm text-weave-500">({positions.length})</span>
        </h2>
        {positions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
            No closed trades yet — nothing to tax.
          </div>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[680px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Acquired</th>
                  <th className="px-4 py-3">Sold</th>
                  <th className="px-4 py-3">Term</th>
                  <th className="px-4 py-3 text-right">Gain / Loss</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const pnl = Number(p.realized_pnl_usd ?? 0);
                  const term = holdingTerm(p.entry_at, p.exit_at);
                  return (
                    <tr key={p.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">{p.ticker}</td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {new Date(p.entry_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 text-xs text-weave-500">
                        {p.exit_at ? new Date(p.exit_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn(
                          "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                          term === "long" ? "bg-treasure-100 text-treasure-700" : "bg-weave-100 text-weave-700"
                        )}>
                          {term}
                        </span>
                      </td>
                      <td className={cn(
                        "px-4 py-3 text-right font-mono font-medium",
                        pnl >= 0 ? "text-emerald-700" : "text-red-700"
                      )}>
                        {pnl >= 0 ? "+" : ""}{usd(pnl)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <TaxStrategySection
        salary={annualIncome}
        retirementContributionPct={retirementContributionPct}
        employerMatchPct={employerMatchPct}
        employerMatchCapPct={employerMatchCapPct}
        realizedYtd={gains.totalRealized}
        withholdingPct={withholdingPct}
        childAccounts={childAccounts}
      />
    </div>
  );
}

function KPI({
  label,
  value,
  tone = "neutral"
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad" | "treasure";
}) {
  const toneClass = {
    neutral: "text-weave-800",
    good: "text-emerald-700",
    bad: "text-red-700",
    treasure: "text-treasure-700"
  }[tone];
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5">
      <p className="text-xs uppercase tracking-widest text-weave-500">{label}</p>
      <p className={cn("mt-2 font-serif text-2xl", toneClass)}>{value}</p>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex justify-between border-b border-weave-50 py-1.5">
      <dt className="text-weave-500">{label}</dt>
      <dd className={cn("font-mono", strong ? "font-semibold text-weave-800" : "text-weave-700")}>
        {value}
      </dd>
    </div>
  );
}
