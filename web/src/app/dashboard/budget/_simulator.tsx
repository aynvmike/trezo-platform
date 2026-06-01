"use client";

import { useState } from "react";
import type { BudgetAnalysis } from "@/lib/budget";

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

/** A labelled range slider with a live readout. */
function Slider({
  label,
  hint,
  min,
  max,
  step,
  value,
  display,
  onChange
}: {
  label: string;
  hint: string;
  min: number;
  max: number;
  step: number;
  value: number;
  display: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label className="text-sm font-medium text-weave-700">{label}</label>
        <span className="font-mono text-sm text-weave-800">{display}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-weave-600"
      />
      <p className="text-xs text-weave-500 leading-relaxed">{hint}</p>
    </div>
  );
}

export function Simulator({ a }: { a: BudgetAnalysis }) {
  const categories = a.byCategory;
  const defaultCat =
    categories.find((c) => c.category === "Food delivery")?.category ??
    categories.find((c) => c.category === "Rideshare")?.category ??
    categories[0]?.category ??
    "";

  const [cat, setCat] = useState(defaultCat);
  const [freq, setFreq] = useState(100);
  const [feePct, setFeePct] = useState(15);
  const [replacement, setReplacement] = useState(0);

  const selected = categories.find((c) => c.category === cat) ?? categories[0];
  if (!selected) return null;

  const months = Math.max(1, a.monthsCovered);
  const currentMonthly = selected.total / months;
  const monthlyOrders = selected.count / months;

  const newMonthly = currentMonthly * (freq / 100);
  const grossSavings = currentMonthly - newMonthly;
  const netSavings = grossSavings - replacement;
  const ordersAvoided = monthlyOrders * (1 - freq / 100);
  const estimatedFees = currentMonthly * (feePct / 100);

  return (
    <section className="space-y-5">
      <div>
        <h2 className="font-serif text-2xl text-weave-800 tracking-tight">
          Savings simulator
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-weave-600 leading-relaxed">
          Pick a habit and model a change. This is not about going without —
          it is about seeing what a smaller change is actually worth.
        </p>
      </div>

      {/* Category picker */}
      <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-5">
        <div className="space-y-1.5">
          <label
            htmlFor="sim-category"
            className="text-sm font-medium text-weave-700"
          >
            Habit to model
          </label>
          <select
            id="sim-category"
            value={cat}
            onChange={(e) => setCat(e.target.value)}
            className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
          >
            {categories.map((c) => (
              <option key={c.category} value={c.category}>
                {c.category} — {usd(c.total / months)}/month
              </option>
            ))}
          </select>
        </div>

        <Slider
          label="Keep this habit at"
          hint="100% is your current habit. Slide down to model ordering less — half, a third, or stopping entirely."
          min={0}
          max={100}
          step={5}
          value={freq}
          display={`${freq}%`}
          onChange={setFreq}
        />

        <Slider
          label="Estimated fees, service charges & tips"
          hint="The share of each order that is not the food or ride itself. Many apps bundle this in — 15-25% is typical."
          min={0}
          max={35}
          step={1}
          value={feePct}
          display={`${feePct}%`}
          onChange={setFeePct}
        />

        <div className="space-y-1.5">
          <label
            htmlFor="sim-replacement"
            className="text-sm font-medium text-weave-700"
          >
            Replacement cost ($/month)
          </label>
          <input
            id="sim-replacement"
            type="number"
            min={0}
            step={25}
            value={replacement}
            onChange={(e) => setReplacement(Math.max(0, Number(e.target.value)))}
            className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
          />
          <p className="text-xs text-weave-500 leading-relaxed">
            Cutting a habit is not free — you still eat, you still travel.
            Add what the replacement costs (groceries, gas, pickup) so the
            savings number stays honest.
          </p>
        </div>
      </div>

      {/* Result */}
      <div className="rounded-xl border border-treasure-200 bg-treasure-50/60 p-5">
        <p className="text-sm text-weave-700 leading-relaxed">
          You spend about{" "}
          <span className="font-medium text-weave-900">
            {usd(currentMonthly)}/month
          </span>{" "}
          on {selected.category.toLowerCase()}. An estimated{" "}
          <span className="font-medium">{usd(estimatedFees)}/month</span> of
          that is fees, service charges, and tips. At{" "}
          <span className="font-medium">{freq}%</span> of your current habit
          you would spend {usd(newMonthly)}/month — about{" "}
          <span className="font-medium">
            {ordersAvoided.toFixed(0)} fewer
          </span>{" "}
          orders a month.
        </p>
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Stat label="Gross savings / month" value={usd(grossSavings)} tone="good" />
          <Stat label="Replacement cost" value={`-${usd(replacement)}`} />
          <Stat
            label="Net savings / month"
            value={usd(netSavings)}
            tone={netSavings >= 0 ? "good" : "bad"}
          />
          <Stat
            label="Net savings / year"
            value={usd(netSavings * 12)}
            tone={netSavings >= 0 ? "good" : "bad"}
          />
        </div>
        <p className="mt-4 text-xs text-weave-500 leading-relaxed">
          Use the Goal planner below to turn this net amount into a goal and
          route it into your Trezo account, KINDRIP, or a standalone goal — so
          the money you free up starts working instead of just sitting still.
        </p>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  tone = "neutral"
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad";
}) {
  const toneClass = {
    neutral: "text-weave-800",
    good: "text-emerald-700",
    bad: "text-red-700"
  }[tone];
  return (
    <div className="rounded-lg border border-weave-100 bg-white p-3">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">
        {label}
      </p>
      <p className={`mt-1 font-mono text-lg font-medium ${toneClass}`}>
        {value}
      </p>
    </div>
  );
}
