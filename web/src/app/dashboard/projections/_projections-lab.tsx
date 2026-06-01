"use client";

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// ---------- math --------------------------------------------------------

function fv(P: number, M: number, r: number, years: number): number {
  // Monthly compounding with end-of-month contributions.
  const m = r / 12;
  const n = years * 12;
  if (m === 0) return P + M * n;
  return P * Math.pow(1 + m, n) + (M * (Math.pow(1 + m, n) - 1)) / m;
}

type Inputs = {
  start: number;       // starting balance
  monthly: number;     // monthly contribution
  ret: number;         // expected annual return (e.g. 0.08)
  years: number;       // horizon
  ordRate: number;     // ordinary-income tax bracket (e.g. 0.22)
  ltcgRate: number;    // long-term capital-gains rate (e.g. 0.15)
  tlhOn: boolean;      // tax-loss harvesting
  donatePct: number;   // % of unrealised gains donated at end (0..1)
};

type AccountKey =
  | "taxable"
  | "roth"
  | "roth401k"
  | "traditional"
  | "sepIra"
  | "hsa"
  | "fiveTwoNine"
  | "futureIndex"
  | "annuity"
  | "iBonds";

type AccountSpec = {
  key: AccountKey;
  label: string;
  tagline: string;
  body: string;
};

const ACCOUNTS: AccountSpec[] = [
  {
    key: "taxable",
    label: "Taxable brokerage",
    tagline: "Flexible · taxed yearly + at sale",
    body:
      "Most flexible — no contribution cap, no withdrawal age. The downside is tax drag: realised gains and dividends are taxed every year, and when you sell, long-term gains are taxed too. Tax-loss harvesting and donating appreciated shares directly to charity are the two biggest mitigations."
  },
  {
    key: "roth",
    label: "Roth IRA",
    tagline: "Pay tax now · grow & withdraw tax-free",
    body:
      "You pay tax on the dollars going in, then nothing on growth and nothing on qualified withdrawals after 59½. The best account in the country for younger investors with a long horizon. Annual contribution limits apply."
  },
  {
    key: "traditional",
    label: "Traditional IRA / 401(k)",
    tagline: "Save tax now · pay on withdrawal",
    body:
      "Contributions reduce taxable income today; growth is untaxed; withdrawals in retirement are taxed as ordinary income. Best when your tax bracket today is higher than it will be in retirement."
  },
  {
    key: "futureIndex",
    label: "Future Index Account",
    tagline: "Child wealth · tax-advantaged",
    body:
      "Trezo's name for the OBBB child accounts (a custodial / Roth-style wrapper for a minor). Long horizon, growth tax-advantaged when used for the child's benefit. The KINDRIP layer feeds this."
  },
  {
    key: "annuity",
    label: "Deferred annuity",
    tagline: "Tax-deferred · ordinary-income on gains",
    body:
      "An insurance contract: money grows tax-deferred while inside, then gains are taxed as ordinary income when withdrawn. A fixed-indexed annuity also protects your principal. Long-horizon vehicle — useful for the retirement bucket, not a daily trade."
  },
  {
    key: "roth401k",
    label: "Roth 401(k)",
    tagline: "Workplace · pay tax now · grow tax-free",
    body:
      "Like a Roth IRA but inside your employer's 401(k) plan. You pay tax on contributions, then nothing on growth or qualified withdrawals after 59½. Much higher annual contribution limit than a Roth IRA — useful if you have access at work."
  },
  {
    key: "sepIra",
    label: "SEP-IRA / Solo 401(k)",
    tagline: "Self-employed · pretax in · ordinary-income out",
    body:
      "Retirement accounts for self-employed or 1099 income. Contributions are pretax (reduce taxable income now); growth is untaxed; withdrawals taxed as ordinary income. Contribution limits are far higher than a regular IRA — up to ~25% of self-employment income."
  },
  {
    key: "hsa",
    label: "HSA (Health Savings)",
    tagline: "Triple tax-advantaged · best account in the code",
    body:
      "Often called the best account in the tax code. Contributions are tax-deductible, growth is untaxed, and withdrawals for qualified medical expenses are tax-free. After 65 you can also withdraw for any reason (taxed as ordinary income, like a Traditional IRA). Requires a high-deductible health plan."
  },
  {
    key: "fiveTwoNine",
    label: "529 College Savings",
    tagline: "Education · federal tax-free for qualified use",
    body:
      "An education savings account. Federal tax-free growth and withdrawals for qualified education expenses (school, tuition, even up to $10k/yr K-12). Many states also give a state-tax deduction on contributions. If used for non-education, gains are taxed plus a 10% penalty."
  },
  {
    key: "iBonds",
    label: "Series I Savings Bonds",
    tagline: "Inflation-linked · tax-deferred · state-tax exempt",
    body:
      "U.S. Treasury bonds whose rate adjusts with inflation. Interest grows tax-deferred while held and is exempt from state and local tax. You can buy up to $10,000 a year through TreasuryDirect. Real return is typically 1–2% above inflation — the projection caps the assumed return at 4% to stay honest."
  }
];

const COLORS: Record<AccountKey, string> = {
  taxable: "#f87171",
  roth: "#10b981",
  roth401k: "#059669",
  traditional: "#6c8e7f",
  sepIra: "#475569",
  hsa: "#0ea5e9",
  fiveTwoNine: "#8b5cf6",
  futureIndex: "#a78bfa",
  annuity: "#f59e0b",
  iBonds: "#94a3b8"
};

function projectSeries(account: AccountKey, x: Inputs): number[] {
  const series: number[] = [];
  for (let y = 0; y <= x.years; y++) {
    series.push(projectAt(account, x, y));
  }
  return series;
}

function projectAt(account: AccountKey, x: Inputs, year: number): number {
  const contributed = x.start + x.monthly * 12 * year;
  switch (account) {
    case "taxable": {
      // Annual tax drag — assume ~30% of the year's gains realised and
      // taxed at LTCG. Tax-loss harvesting trims that drag by ~30%.
      const drag = x.ret * 0.3 * x.ltcgRate * (x.tlhOn ? 0.7 : 1);
      const gross = fv(x.start, x.monthly, x.ret - drag, year);
      const unrealised = Math.max(0, gross - contributed);
      // What stays unrealised gets taxed if you liquidate today; donating
      // appreciated shares directly to charity removes that slice from
      // the tax bill entirely.
      const taxableShare = unrealised * 0.7 * (1 - x.donatePct);
      return gross - taxableShare * x.ltcgRate;
    }
    case "roth":
    case "roth401k":
    case "hsa":
    case "fiveTwoNine":
    case "futureIndex":
      // Roth-style: growth and qualified withdrawals are tax-free.
      // HSA assumes medical-purpose withdrawals; 529 assumes education.
      // Future Index assumes the funds are used for the child's benefit.
      return fv(x.start, x.monthly, x.ret, year);
    case "traditional":
    case "sepIra": {
      // Pretax in, ordinary income on withdrawal. Simplification: whole
      // balance taxed at the ordinary bracket on exit.
      const gross = fv(x.start, x.monthly, x.ret, year);
      return gross * (1 - x.ordRate);
    }
    case "annuity": {
      const gross = fv(x.start, x.monthly, x.ret, year);
      const gains = Math.max(0, gross - contributed);
      return gross - gains * x.ordRate;
    }
    case "iBonds": {
      // I-bonds: inflation-linked, capped at a realistic 4% nominal so
      // the comparison stays honest. Tax-deferred, ordinary income on
      // gains at redemption, state-tax exempt (no model adjustment).
      const capped = Math.min(x.ret, 0.04);
      const gross = fv(x.start, x.monthly, capped, year);
      const gains = Math.max(0, gross - contributed);
      return gross - gains * x.ordRate;
    }
  }
}

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

// ---------- component ---------------------------------------------------

export function ProjectionsLab() {
  const [start, setStart] = useState(10_000);
  const [monthly, setMonthly] = useState(500);
  const [retPct, setRetPct] = useState(8);
  const [years, setYears] = useState(20);
  const [ordPct, setOrdPct] = useState(22);
  const [ltcgPct, setLtcgPct] = useState(15);
  const [tlhOn, setTlhOn] = useState(false);
  const [donatePctUI, setDonatePctUI] = useState(0);
  // Chart-type toggle — line clumps the curves together, bars give a
  // clean at-a-glance ranking, pie shows each account's share of the
  // final pot. All three render off the same `series` / `endings` math.
  const [chartMode, setChartMode] = useState<"lines" | "bars" | "pie">("lines");

  const inputs: Inputs = useMemo(
    () => ({
      start,
      monthly,
      ret: retPct / 100,
      years,
      ordRate: ordPct / 100,
      ltcgRate: ltcgPct / 100,
      tlhOn,
      donatePct: donatePctUI / 100
    }),
    [start, monthly, retPct, years, ordPct, ltcgPct, tlhOn, donatePctUI]
  );

  // End balances + per-year series for the chart.
  const series = useMemo(
    () =>
      Object.fromEntries(
        ACCOUNTS.map((a) => [a.key, projectSeries(a.key, inputs)])
      ) as Record<AccountKey, number[]>,
    [inputs]
  );

  const endings = useMemo(
    () =>
      ACCOUNTS.map((a) => ({
        ...a,
        end: series[a.key][series[a.key].length - 1]
      })),
    [series]
  );

  const baseline =
    endings.find((e) => e.key === "taxable")?.end ?? 0;
  const sorted = [...endings].sort((a, b) => b.end - a.end);
  const winner = sorted[0];
  const taxablesIdx = sorted.findIndex((s) => s.key === "taxable");

  return (
    <div className="space-y-6">
      {/* Inputs */}
      <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-4">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h2 className="font-serif text-xl text-weave-800">Your assumptions</h2>
          <span className="text-[10px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5">
            Live · chart & cards update as you drag
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          <NumberField
            id="proj-start"
            label="Starting balance ($)"
            min={0}
            max={10_000_000}
            step={500}
            value={start}
            onChange={setStart}
          />
          <NumberField
            id="proj-monthly"
            label="Monthly add ($)"
            min={0}
            max={50_000}
            step={50}
            value={monthly}
            onChange={setMonthly}
          />
          <NumberField
            id="proj-ret"
            label="Expected return (%)"
            min={0}
            max={20}
            step={0.5}
            value={retPct}
            onChange={setRetPct}
          />
          <NumberField
            id="proj-years"
            label="Time horizon (years)"
            min={1}
            max={50}
            step={1}
            value={years}
            onChange={setYears}
          />
          <NumberField
            id="proj-ord"
            label="Income bracket (%)"
            min={0}
            max={50}
            step={1}
            value={ordPct}
            onChange={setOrdPct}
          />
          <NumberField
            id="proj-ltcg"
            label="Long-term gains (%)"
            min={0}
            max={30}
            step={1}
            value={ltcgPct}
            onChange={setLtcgPct}
          />
        </div>

        {/* What-if toggles */}
        <div className="border-t border-weave-50 pt-4 grid gap-3 sm:grid-cols-2">
          <Toggle
            on={tlhOn}
            onChange={setTlhOn}
            label="Tax-loss harvesting on taxable"
            sub="Sell losers each year to offset gains — trims the yearly tax drag by ~30%."
          />
          <div className="space-y-1.5">
            <Label htmlFor="proj-donate" className="text-xs">
              Donate appreciated shares (% of end gains)
            </Label>
            <Input
              id="proj-donate"
              type="number"
              min={0}
              max={100}
              step={5}
              value={donatePctUI}
              onChange={(e) => setDonatePctUI(Number(e.target.value))}
            />
            <p className="text-[11px] text-weave-500 leading-relaxed">
              Giving appreciated shares directly to a charity (instead of
              cash) removes that slice of taxable gains entirely.
            </p>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-3">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h2 className="font-serif text-xl text-weave-800">
            After-tax growth over {years} years
          </h2>
          <div className="flex items-center gap-1.5">
            {(["lines", "bars", "pie"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setChartMode(m)}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-[11px] font-medium transition capitalize",
                  chartMode === m
                    ? "border-weave-400 bg-weave-100 text-weave-800"
                    : "border-weave-200 bg-white text-weave-600 hover:bg-weave-50"
                )}
                title={
                  m === "lines"
                    ? "Growth lines from year 0 to year N"
                    : m === "bars"
                      ? "End balances side-by-side — easiest at-a-glance read"
                      : "Pie of each account's share of the total final pot"
                }
              >
                {m === "lines" ? "Lines" : m === "bars" ? "Bars" : "Pie"}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-weave-500">
          {chartMode === "lines"
            ? "Lines show what you keep — not the gross balance."
            : chartMode === "bars"
              ? `Each bar is the final after-tax balance at year ${years}. Largest on the left.`
              : `Pie shows each account's share of the combined final pot. The biggest slice is the strongest wrapper for your inputs.`}
        </p>
        {chartMode === "lines" && (
          <ProjectionChart series={series} years={years} />
        )}
        {chartMode === "bars" && (
          <ProjectionBars endings={endings} />
        )}
        {chartMode === "pie" && (
          <ProjectionPie endings={endings} />
        )}
        <Legend />
      </div>

      {/* Cards */}
      <section className="space-y-3">
        <h2 className="font-serif text-xl text-weave-800">
          The five accounts, side by side
        </h2>
        <div className="grid gap-3 lg:grid-cols-2">
          {ACCOUNTS.map((a) => {
            const end = endings.find((e) => e.key === a.key)?.end ?? 0;
            const delta = end - baseline;
            return (
              <AccountCard
                key={a.key}
                spec={a}
                end={end}
                delta={a.key === "taxable" ? null : delta}
              />
            );
          })}
        </div>
      </section>

      {/* Insight */}
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 space-y-1.5">
        <p className="text-sm font-medium text-emerald-900">
          Top pick over {years} years: {winner.label} — {usd(winner.end)}
        </p>
        <p className="text-sm text-emerald-900/90 leading-relaxed">
          {winner.key === "taxable" ? (
            <>The taxable brokerage came out on top here — usually means the
            tax assumptions are gentle. Try raising the income or capital-
            gains rate.</>
          ) : (
            <>
              That is{" "}
              <span className="font-medium">
                {usd(winner.end - baseline)} more
              </span>{" "}
              than the same money in a plain taxable brokerage. Over{" "}
              {years} years, the right account wrapper can be worth as
              much as the right strategy.
            </>
          )}
        </p>
        {taxablesIdx > 0 && (
          <p className="text-xs text-emerald-900/80">
            (Taxable came in #{taxablesIdx + 1} of {ACCOUNTS.length}.)
          </p>
        )}
      </div>
    </div>
  );
}

// ---------- pieces ------------------------------------------------------

function NumberField({
  id,
  label,
  min,
  max,
  step,
  value,
  onChange
}: {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (n: number) => void;
}) {
  // Number input + paired range slider. The slider drives the same
  // state as the input, so dragging it makes the chart and cards
  // recompute in real time — the typing path stays for precise values.
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <input
        type="range"
        aria-label={`${label} slider`}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-treasure-600 cursor-pointer"
      />
    </div>
  );
}

function Toggle({
  on,
  onChange,
  label,
  sub
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  label: string;
  sub: string;
}) {
  return (
    <label className="flex items-start gap-2.5 cursor-pointer">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-weave-300 accent-treasure-600"
      />
      <span>
        <span className="block text-sm text-weave-700">{label}</span>
        <span className="block text-[11px] text-weave-500 leading-relaxed">
          {sub}
        </span>
      </span>
    </label>
  );
}

function AccountCard({
  spec,
  end,
  delta
}: {
  spec: AccountSpec;
  end: number;
  delta: number | null;
}) {
  return (
    <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-2">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h3 className="font-medium text-weave-800">{spec.label}</h3>
        <span
          className="inline-flex h-3 w-3 rounded-full"
          style={{ backgroundColor: COLORS[spec.key] }}
          aria-hidden="true"
        />
      </div>
      <p className="text-[11px] uppercase tracking-widest text-weave-500">
        {spec.tagline}
      </p>
      <p className="font-mono text-2xl font-medium text-weave-800">
        {usd(end)}
      </p>
      {delta !== null && (
        <p
          className={cn(
            "text-xs font-mono",
            delta >= 0 ? "text-emerald-700" : "text-red-600"
          )}
        >
          {delta >= 0 ? "+" : ""}
          {usd(delta)} vs taxable
        </p>
      )}
      <p className="text-sm text-weave-600 leading-relaxed">{spec.body}</p>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-weave-600">
      {ACCOUNTS.map((a) => (
        <span key={a.key} className="flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: COLORS[a.key] }}
          />
          {a.label}
        </span>
      ))}
    </div>
  );
}

function ProjectionChart({
  series,
  years
}: {
  series: Record<AccountKey, number[]>;
  years: number;
}) {
  const W = 720;
  const H = 260;
  const padX = 40;
  const padY = 18;
  const all: number[] = [];
  for (const k of Object.keys(series) as AccountKey[]) {
    for (const v of series[k]) all.push(v);
  }
  const hi = Math.max(...all, 1);
  const lo = 0;
  const n = years;

  const xf = (i: number) => padX + (i / n) * (W - 2 * padX);
  const yf = (v: number) =>
    padY + (1 - (v - lo) / (hi - lo || 1)) * (H - 2 * padY);

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => lo + t * (hi - lo));
  const xTicks = Array.from({ length: 5 }, (_, i) =>
    Math.round((i * years) / 4)
  );

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label="After-tax projected balance by account type"
    >
      {/* gridlines */}
      {yTicks.map((v, i) => (
        <g key={`gy-${i}`}>
          <line
            x1={padX}
            x2={W - padX}
            y1={yf(v)}
            y2={yf(v)}
            stroke="#eaeaea"
            strokeDasharray="2 4"
          />
          <text
            x={padX - 6}
            y={yf(v) + 3}
            textAnchor="end"
            fontSize="10"
            fill="#888"
          >
            {usd(v)}
          </text>
        </g>
      ))}
      {xTicks.map((y, i) => (
        <text
          key={`gx-${i}`}
          x={xf(y)}
          y={H - 4}
          textAnchor="middle"
          fontSize="10"
          fill="#888"
        >
          {y}y
        </text>
      ))}

      {(Object.keys(series) as AccountKey[]).map((k) => {
        const pts = series[k]
          .map((v, i) => `${xf(i)},${yf(v)}`)
          .join(" ");
        return (
          <polyline
            key={k}
            points={pts}
            fill="none"
            stroke={COLORS[k]}
            strokeWidth={2}
          />
        );
      })}
    </svg>
  );
}

function ProjectionBars({ endings }: { endings: { key: AccountKey; label: string; end: number }[] }) {
  // Sorted high-to-low so the strongest wrapper is the first read.
  const sorted = [...endings].sort((a, b) => b.end - a.end);
  const max = Math.max(...sorted.map((e) => e.end), 1);
  const W = 720;
  const rowH = 28;
  const padX = 160;
  const H = sorted.length * rowH + 12;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label="Final after-tax balance per account, ranked"
    >
      {sorted.map((e, i) => {
        const y = i * rowH + 6;
        const w = ((W - padX - 24) * e.end) / max;
        return (
          <g key={e.key}>
            <text
              x={padX - 8}
              y={y + rowH * 0.6}
              textAnchor="end"
              fontSize="11"
              fill="currentColor"
              className="text-weave-700"
            >
              {e.label}
            </text>
            <rect
              x={padX}
              y={y + 4}
              width={Math.max(w, 1)}
              height={rowH - 12}
              rx={3}
              fill={COLORS[e.key]}
              opacity={0.85}
            />
            <text
              x={padX + Math.max(w, 1) + 6}
              y={y + rowH * 0.6}
              fontSize="11"
              fill="currentColor"
              className="text-weave-700 font-mono"
            >
              {usd(e.end)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ProjectionPie({ endings }: { endings: { key: AccountKey; label: string; end: number }[] }) {
  // Pie of the final-balance share. The biggest slice = the wrapper
  // that compounded the most against the chosen assumptions.
  const total = endings.reduce((s, e) => s + Math.max(0, e.end), 0) || 1;
  const r = 110;
  const cx = 160;
  const cy = 140;
  const W = 720;
  const H = 280;
  let a0 = -Math.PI / 2; // start at 12 o'clock
  const slices = endings.map((e) => {
    const frac = Math.max(0, e.end) / total;
    const a1 = a0 + frac * Math.PI * 2;
    const x0 = cx + r * Math.cos(a0);
    const y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1);
    const y1 = cy + r * Math.sin(a1);
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1} Z`;
    const out = { key: e.key, label: e.label, end: e.end, frac, d };
    a0 = a1;
    return out;
  });
  const sortedForLegend = [...slices].sort((a, b) => b.end - a.end);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label="Final after-tax share by account"
    >
      {slices.map((s) =>
        s.frac > 0 ? (
          <path
            key={s.key}
            d={s.d}
            fill={COLORS[s.key]}
            opacity={0.9}
            stroke="white"
            strokeWidth={1.5}
          />
        ) : null
      )}
      {sortedForLegend.map((s, i) => {
        const y = 18 + i * 22;
        return (
          <g key={`l-${s.key}`}>
            <rect x={300} y={y - 10} width={12} height={12} rx={2} fill={COLORS[s.key]} />
            <text x={320} y={y} fontSize="11" fill="currentColor" className="text-weave-700">
              {s.label}
            </text>
            <text
              x={W - 12}
              y={y}
              textAnchor="end"
              fontSize="11"
              fill="currentColor"
              className="text-weave-600 font-mono"
            >
              {(s.frac * 100).toFixed(1)}% · {usd(s.end)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
