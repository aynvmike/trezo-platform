// Tax Strategy section — the educational half of the Tax page.
//
// Phase 9.5b; Phase 12 follow-up — the long reference blocks (accounts,
// strategies, glide path) are now collapsible so the page stays short.
// Educational only: it shows what each move is and the numbers behind
// it — never a personalized "you should". A pure server component.

import Link from "next/link";
import { cn } from "@/lib/utils";
import { Disclosure } from "@/components/ui/disclosure";
import {
  TAX_ADVANTAGED_ACCOUNTS,
  TAX_STRATEGIES,
  GLIDE_PATH_STAGES,
  employerMatchValue,
  matchSummary,
  withholdingNote,
  childAccountTaxNote
} from "@/lib/tax-strategy";

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

export function TaxStrategySection({
  salary,
  retirementContributionPct,
  employerMatchPct,
  employerMatchCapPct,
  realizedYtd,
  withholdingPct,
  childAccounts
}: {
  salary: number;
  retirementContributionPct: number;
  employerMatchPct: number;
  employerMatchCapPct: number;
  realizedYtd: number;
  withholdingPct: number;
  childAccounts: {
    childCount: number;
    contributedYtd: number;
    totalContributed: number;
  };
}) {
  const match = employerMatchValue(
    salary,
    retirementContributionPct,
    employerMatchPct,
    employerMatchCapPct
  );
  const haveMatchInputs = salary > 0 && employerMatchCapPct > 0;
  const gains = Math.max(0, realizedYtd);

  return (
    <section className="space-y-6">
      <header>
        <h2 className="font-serif text-2xl text-weave-800 tracking-tight">
          Tax Strategy
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-weave-600 leading-relaxed">
          Keeping more of what you build is its own kind of return. Below is
          how the tax-advantaged accounts and money-saving moves work, in
          plain language and with the math. This is information to learn
          from and take to a CPA — not personalized advice.
        </p>
      </header>

      {/* Employer match — the "free money" math */}
      <div className="rounded-xl border border-weave-100 bg-white p-5">
        <h3 className="font-medium text-weave-800">
          Your employer match — the free money check
        </h3>
        {haveMatchInputs ? (
          <div className="mt-3 space-y-3">
            <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
              <Row label="Salary" value={usd(match.salary)} />
              <Row
                label="You contribute"
                value={`${match.contributionPct}% — ${usd(match.employeeContribution)}`}
              />
              <Row
                label="Employer adds now"
                value={usd(match.employerMatch)}
                strong
              />
              <Row
                label="Full match available"
                value={usd(match.fullPotentialMatch)}
              />
            </dl>
            <div
              className={cn(
                "rounded-lg p-3 text-sm leading-relaxed",
                match.capturingFullMatch
                  ? "bg-emerald-50 text-emerald-900 border border-emerald-200"
                  : "bg-amber-50 text-amber-900 border border-amber-200"
              )}
            >
              {matchSummary(match)}
            </div>
          </div>
        ) : (
          <p className="mt-3 text-sm text-weave-500 leading-relaxed">
            Add your salary and your employer&apos;s match details in{" "}
            <Link
              href="/dashboard/settings/profile"
              className="underline text-weave-700"
            >
              Profile settings
            </Link>{" "}
            and Trezo will show exactly how much free money the match is
            worth — and whether you are leaving any of it on the table.
          </p>
        )}
      </div>

      {/* Withholding on trading gains */}
      <div className="rounded-xl border border-weave-100 bg-white p-5">
        <h3 className="font-medium text-weave-800">
          Setting tax aside on trading gains
        </h3>
        <p className="mt-3 text-sm text-weave-600 leading-relaxed">
          {gains > 0
            ? withholdingNote(gains, withholdingPct)
            : "A paycheck has tax withheld automatically, but trading gains do not. Once this year shows realized gains, Trezo will estimate what to set aside so there is no surprise bill — and the quarterly table above already breaks it down."}
        </p>
      </div>

      {/* Child accounts (KINDRIP) — the tax treatment of contributions */}
      <div className="rounded-xl border border-weave-100 bg-white p-5">
        <h3 className="font-medium text-weave-800">
          Child accounts (KINDRIP)
        </h3>
        {childAccounts.childCount > 0 && childAccounts.contributedYtd > 0 && (
          <dl className="mt-3 grid sm:grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
            <Row
              label="Moved into child accounts this year"
              value={usd(childAccounts.contributedYtd)}
              strong
            />
            <Row
              label="Total contributed, all time"
              value={usd(childAccounts.totalContributed)}
            />
          </dl>
        )}
        <p className="mt-3 text-sm text-weave-600 leading-relaxed">
          {childAccountTaxNote(
            childAccounts.contributedYtd,
            childAccounts.totalContributed,
            childAccounts.childCount
          )}
        </p>
      </div>

      {/* Tax-advantaged accounts — collapsed into a single outer
          Disclosure (Mike feedback 2026-05-28: too many stacked toggle
          headers made the page feel dense). Each account is a
          sub-Disclosure inside, so users can still drill into the one
          they care about — but the page stops shouting the full list. */}
      <Disclosure
        title="Tax-advantaged accounts"
        hint={`${TAX_ADVANTAGED_ACCOUNTS.length} account types — reference`}
      >
        <p className="text-weave-500 leading-relaxed mb-3">
          The accounts the tax code rewards you for using — what each is
          for, who benefits most, and the numbers. Open the one you want
          to learn about.
        </p>
        <div className="space-y-2">
          {TAX_ADVANTAGED_ACCOUNTS.map((a) => (
            <Disclosure key={a.id} title={a.name}>
              <p className="text-weave-600 leading-relaxed">{a.what}</p>
              <p className="mt-2 text-treasure-700 leading-relaxed">{a.why}</p>
              <ul className="mt-3 space-y-1">
                {a.facts.map((f, i) => (
                  <li key={i} className="flex gap-2 text-xs text-weave-500 leading-relaxed">
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
        </div>
      </Disclosure>

      {/* Tax-saving strategies — collapsed */}
      <Disclosure title="Tax-saving strategies" hint={`${TAX_STRATEGIES.length} moves`}>
        <div className="divide-y divide-weave-50 -my-1">
          {TAX_STRATEGIES.map((s) => (
            <div key={s.id} className="py-3">
              <p className="font-medium text-weave-800">{s.name}</p>
              <p className="mt-1 text-weave-600 leading-relaxed">{s.what}</p>
              <p className="mt-1 text-treasure-700 leading-relaxed">{s.why}</p>
              <p className="mt-1.5 text-xs text-weave-400">
                Most useful for: {s.appliesTo}
              </p>
            </div>
          ))}
        </div>
      </Disclosure>

      {/* Age-based glide path — collapsed */}
      <Disclosure title="The age-based glide path" hint="how KINDRIP's Auto mode shifts with age">
        <p className="text-weave-500 mb-3 max-w-2xl leading-relaxed">
          A child&apos;s money does not need the same mix at age 3 and age
          17. KINDRIP&apos;s Auto mode glides from mostly stocks toward bonds
          and cash as college nears — the same model a 529 plan uses, so a
          rough market year right before tuition cannot undo years of saving.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {GLIDE_PATH_STAGES.map((g) => (
            <div
              key={g.label}
              className="rounded-xl border border-weave-100 bg-treasure-50/50 p-4"
            >
              <p className="text-xs uppercase tracking-widest text-treasure-600">
                {g.ageRange}
              </p>
              <p className="mt-1 font-medium text-weave-800">{g.label}</p>
              <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-weave-100">
                <div className="bg-treasure-500" style={{ width: `${g.stocksPct}%` }} />
                <div className="bg-weave-400" style={{ width: `${g.bondsPct}%` }} />
              </div>
              <p className="mt-1.5 text-xs text-weave-500">
                {g.stocksPct}% stocks · {g.bondsPct}% bonds &amp; cash
              </p>
              <p className="mt-2 text-xs text-weave-500 leading-relaxed">{g.note}</p>
            </div>
          ))}
        </div>
      </Disclosure>
    </section>
  );
}

function Row({
  label,
  value,
  strong
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex justify-between border-b border-weave-50 py-1.5">
      <dt className="text-weave-500">{label}</dt>
      <dd
        className={cn(
          "font-mono",
          strong ? "font-semibold text-weave-800" : "text-weave-700"
        )}
      >
        {value}
      </dd>
    </div>
  );
}
