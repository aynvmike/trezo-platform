"use client";

import { useMemo, useState } from "react";
import {
  summarize,
  RETURN_SCENARIOS,
  type Scenario
} from "@/lib/kindrip-projection";

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

const SCENARIOS: { id: Scenario; label: string; rate: string }[] = [
  { id: "conservative", label: "Conservative", rate: "5%/yr" },
  { id: "expected", label: "Expected", rate: "7%/yr" },
  { id: "strong", label: "Strong", rate: "9%/yr" }
];

export function KindripProjection({
  childName,
  currentValue,
  currentAge,
  defaultMonthly
}: {
  childName: string;
  currentValue: number;
  currentAge: number | null;
  defaultMonthly: number;
}) {
  const [monthly, setMonthly] = useState(Math.max(0, Math.round(defaultMonthly)));
  const [scenario, setScenario] = useState<Scenario>("expected");

  const age = Math.min(currentAge ?? 0, 18);
  const sum = useMemo(
    () => summarize(currentValue, age, monthly, RETURN_SCENARIOS[scenario]),
    [currentValue, age, monthly, scenario]
  );

  if (currentAge === null) {
    return (
      <div className="rounded-lg border border-dashed border-weave-200 bg-treasure-50/50 p-4 text-sm text-weave-500">
        Set {childName}&apos;s birth year in the settings below to see a
        projection of where this account could sit at age 18.
      </div>
    );
  }
  if (currentAge >= 18) {
    return (
      <div className="rounded-lg border border-treasure-100 bg-treasure-50/50 p-4 text-sm text-weave-600">
        {childName} is already 18 — the growth phase of this account is
        complete. The account currently holds {usd(currentValue)}.
      </div>
    );
  }

  // --- chart geometry ---
  const pts = sum.points;
  const n = pts.length;
  const W = 600;
  const H = 168;
  const padT = 12;
  const padB = 26;
  const padX = 10;
  const maxV = Math.max(1, ...pts.map((p) => p.value));
  const x = (i: number) => padX + (n <= 1 ? 0 : i / (n - 1)) * (W - 2 * padX);
  const y = (v: number) => padT + (1 - v / maxV) * (H - padT - padB);

  const valueLine = pts.map((p, i) => `${x(i)},${y(p.value)}`).join(" ");
  const costLine = pts
    .map((p, i) => `${x(i)},${y(currentValue + p.contributed)}`)
    .join(" ");
  const areaPath =
    `M ${x(0)},${y(pts[0].value)} ` +
    pts.map((p, i) => `L ${x(i)},${y(p.value)}`).join(" ") +
    ` L ${x(n - 1)},${H - padB} L ${x(0)},${H - padB} Z`;

  const labelIdx = [0, Math.floor((n - 1) / 2), n - 1];

  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-4">
      <div>
        <h3 className="font-serif text-lg text-weave-800">
          Future projection — to age 18
        </h3>
        <p className="mt-1 text-sm text-weave-500 leading-relaxed">
          If you keep this up, here is where {childName}&apos;s account could
          sit at 18 — built from today&apos;s {usd(currentValue)} balance and
          your contributions, compounding over {sum.yearsLeft} year
          {sum.yearsLeft === 1 ? "" : "s"}.
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1">
          <label className="block text-xs font-medium text-weave-600">
            Contribution per month ($)
          </label>
          <input
            type="number"
            min={0}
            step={25}
            value={monthly}
            onChange={(e) => setMonthly(Math.max(0, Number(e.target.value)))}
            className="w-32 rounded-md border border-weave-200 bg-white px-3 py-1.5 text-sm text-weave-800"
          />
        </div>
        <div className="space-y-1">
          <span className="block text-xs font-medium text-weave-600">
            Market assumption
          </span>
          <div className="flex gap-1">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setScenario(s.id)}
                className={
                  "rounded-md border px-2.5 py-1.5 text-xs transition " +
                  (scenario === s.id
                    ? "border-weave-400 bg-weave-50 text-weave-800"
                    : "border-weave-200 bg-white text-weave-500 hover:bg-weave-50")
                }
                title={`${s.label} — ${s.rate}`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full rounded-lg border border-weave-100 bg-weave-50/40"
        style={{ height: H }}
        role="img"
        aria-label={`Projected account value for ${childName} to age 18`}
      >
        <path d={areaPath} fill="#10b981" fillOpacity={0.14} />
        <polyline
          points={costLine}
          fill="none"
          stroke="#9ca3af"
          strokeWidth={1.5}
          strokeDasharray="4 3"
        />
        <polyline
          points={valueLine}
          fill="none"
          stroke="#10b981"
          strokeWidth={2}
        />
        {labelIdx.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 8}
            textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
            className="fill-weave-500"
            fontSize={10}
          >
            age {pts[i].age}
          </text>
        ))}
      </svg>
      <div className="flex flex-wrap gap-4 text-xs text-weave-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-sm bg-emerald-500" /> Projected value
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 bg-weave-400" /> What you put in
        </span>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg border border-treasure-200 bg-treasure-50/60 p-3">
          <p className="text-[11px] uppercase tracking-widest text-treasure-600">
            At age 18
          </p>
          <p className="mt-1 font-serif text-xl text-weave-800">
            {usd(sum.finalValue)}
          </p>
        </div>
        <div className="rounded-lg border border-weave-100 bg-treasure-50/40 p-3">
          <p className="text-[11px] uppercase tracking-widest text-weave-500">
            You add
          </p>
          <p className="mt-1 font-serif text-xl text-weave-800">
            {usd(sum.totalContributed)}
          </p>
        </div>
        <div className="rounded-lg border border-weave-100 bg-treasure-50/40 p-3">
          <p className="text-[11px] uppercase tracking-widest text-weave-500">
            Growth on top
          </p>
          <p className="mt-1 font-serif text-xl text-emerald-700">
            +{usd(sum.growth)}
          </p>
        </div>
      </div>

      {/* Tax-savings incentive */}
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
        <p className="text-sm font-medium text-emerald-900">
          The tax advantage
        </p>
        <p className="mt-1 text-sm text-emerald-800 leading-relaxed">
          In a Future Index Account these gains compound without the yearly tax
          drag a regular brokerage account faces on dividends and turnover. We
          estimate that is worth about{" "}
          <span className="font-semibold">{usd(sum.taxAdvantage)}</span> more by
          age 18 — money that stays invested for {childName} instead of going to
          tax. Contributions also leave your taxable trading balance the moment
          they move in.
        </p>
        <p className="mt-2 text-[11px] text-emerald-700/80">
          An illustrative estimate, not a guarantee or tax advice — markets and
          tax rules vary. See the{" "}
          <a href="/dashboard/tax" className="underline">
            Tax page
          </a>{" "}
          for the running detail.
        </p>
      </div>
    </div>
  );
}
