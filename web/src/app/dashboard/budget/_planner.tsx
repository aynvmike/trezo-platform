"use client";

import { useState } from "react";
import Link from "next/link";
import type { BudgetAnalysis } from "@/lib/budget";

function usd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  });
}

const INPUT =
  "flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500";

type Destination = {
  id: string;
  label: string;
  note: string;
  href: string | null;
  linkLabel: string;
};

const DESTINATIONS: Destination[] = [
  {
    id: "main",
    label: "My trading account",
    note: "Adds the money to your Trezo trading account, so the bot has more buying power to put to work across the layers.",
    href: "/dashboard/paper",
    linkLabel: "Open Paper Trading"
  },
  {
    id: "kindrip",
    label: "A KINDRIP child account",
    note: "Routes it into a child's Future Index Account. Set that child's monthly contribution to this amount on the KINDRIP page.",
    href: "/dashboard/kindrip",
    linkLabel: "Open KINDRIP"
  },
  {
    id: "goal",
    label: "A standalone savings goal",
    note: "Keep it as its own goal, tracked right here — money set aside before it is committed anywhere.",
    href: null,
    linkLabel: ""
  }
];

type Preset = {
  id: string;
  label: string;
  spendLabel: string;
  altLabel: string;
  spend: number | null; // null = fill from the uploaded data
  alt: number;
};

const PRESETS: Preset[] = [
  { id: "custom", label: "Custom comparison", spendLabel: "", altLabel: "", spend: 0, alt: 0 },
  {
    id: "car",
    label: "Rideshare & delivery vs. owning a car",
    spendLabel: "Rideshare & delivery",
    altLabel: "Owning a car (all-in)",
    spend: null,
    alt: 450
  },
  {
    id: "coffee",
    label: "Coffee out vs. brewing at home",
    spendLabel: "Coffee bought out",
    altLabel: "Brewing at home",
    spend: 120,
    alt: 25
  },
  {
    id: "atm",
    label: "ATM & card fees vs. paying direct",
    spendLabel: "ATM & card fees",
    altLabel: "Paying direct (no fees)",
    spend: 30,
    alt: 0
  }
];

export function Planner({ a }: { a: BudgetAnalysis | null }) {
  // --- Goal planner ---
  const [goalName, setGoalName] = useState("");
  const [target, setTarget] = useState(5000);
  const [monthly, setMonthly] = useState(300);
  const [dest, setDest] = useState("main");

  // --- Spending comparison (works with or without uploaded data) ---
  const cats = a?.byCategory ?? [];
  const months = Math.max(1, a?.monthsCovered ?? 1);
  const appMonthly =
    cats
      .filter((c) => c.category === "Rideshare" || c.category === "Food delivery")
      .reduce((s, c) => s + c.total, 0) / months;

  const [preset, setPreset] = useState("custom");
  const [spendLabel, setSpendLabel] = useState("");
  const [spendAmount, setSpendAmount] = useState(0);
  const [altLabel, setAltLabel] = useState("");
  const [altAmount, setAltAmount] = useState(0);

  function applyPreset(id: string) {
    setPreset(id);
    const p = PRESETS.find((x) => x.id === id);
    if (!p) return;
    setSpendLabel(p.spendLabel);
    setAltLabel(p.altLabel);
    setSpendAmount(p.spend === null ? Math.round(appMonthly) : p.spend);
    setAltAmount(p.alt);
  }

  const goalMonths = monthly > 0 ? Math.ceil(target / monthly) : 0;
  const reachDate = new Date();
  if (goalMonths > 0) reachDate.setMonth(reachDate.getMonth() + goalMonths);
  const destination = DESTINATIONS.find((d) => d.id === dest) ?? DESTINATIONS[0];

  const freedMonthly = spendAmount - altAmount;

  return (
    <section className="space-y-8">
      {/* Goal planner */}
      <div className="space-y-4">
        <div>
          <h2 className="font-serif text-2xl text-weave-800 tracking-tight">
            Goal planner
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-weave-600 leading-relaxed">
            Turn the money you free up into something real. Set a goal and a
            monthly amount, and pick where it should go.
          </p>
        </div>

        <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-4">
          <div className="grid sm:grid-cols-3 gap-4">
            <Field label="Goal">
              <input
                type="text"
                value={goalName}
                onChange={(e) => setGoalName(e.target.value)}
                placeholder="e.g. Emergency fund, a boat"
                maxLength={48}
                className={INPUT}
              />
            </Field>
            <Field label="Target amount ($)">
              <input
                type="number"
                min={0}
                step={250}
                value={target}
                onChange={(e) => setTarget(Math.max(0, Number(e.target.value)))}
                className={INPUT}
              />
            </Field>
            <Field label="Set aside per month ($)">
              <input
                type="number"
                min={0}
                step={25}
                value={monthly}
                onChange={(e) => setMonthly(Math.max(0, Number(e.target.value)))}
                className={INPUT}
              />
            </Field>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium text-weave-700">
              Where should this money go?
            </p>
            <div className="grid sm:grid-cols-3 gap-3">
              {DESTINATIONS.map((d) => (
                <label
                  key={d.id}
                  className={
                    "cursor-pointer rounded-xl border p-3 transition " +
                    (dest === d.id
                      ? "border-weave-400 bg-weave-50 ring-1 ring-weave-200"
                      : "border-weave-100 bg-white hover:bg-weave-50")
                  }
                >
                  <input
                    type="radio"
                    name="destination"
                    value={d.id}
                    checked={dest === d.id}
                    onChange={() => setDest(d.id)}
                    className="sr-only"
                  />
                  <span className="block text-sm font-medium text-weave-800">
                    {d.label}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-treasure-200 bg-treasure-50/60 p-5">
          {monthly <= 0 || target <= 0 ? (
            <p className="text-sm text-weave-600">
              Enter a target amount and a monthly amount to see the plan.
            </p>
          ) : (
            <>
              <p className="text-sm text-weave-700 leading-relaxed">
                Setting aside{" "}
                <span className="font-medium text-weave-900">
                  {usd(monthly)}/month
                </span>{" "}
                reaches{" "}
                <span className="font-medium text-weave-900">
                  {goalName.trim() || "your goal"}
                </span>{" "}
                of {usd(target)} in about{" "}
                <span className="font-medium text-weave-900">
                  {goalMonths} month{goalMonths === 1 ? "" : "s"}
                </span>{" "}
                — around{" "}
                {reachDate.toLocaleString(undefined, {
                  month: "long",
                  year: "numeric"
                })}
                . That is roughly {usd(monthly / 4.33)} a week.
              </p>
              <div className="mt-4 rounded-lg border border-weave-100 bg-white p-3">
                <p className="text-sm text-weave-700 leading-relaxed">
                  <span className="font-medium">
                    Destination — {destination.label}:
                  </span>{" "}
                  {destination.note}
                </p>
                {destination.href && (
                  <Link
                    href={destination.href}
                    className="mt-2 inline-block text-sm text-weave-700 underline hover:text-weave-900"
                  >
                    {destination.linkLabel} →
                  </Link>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Spending comparison */}
      <div className="space-y-4">
        <div>
          <h2 className="font-serif text-2xl text-weave-800 tracking-tight">
            Spending comparison
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-weave-600 leading-relaxed">
            Weigh one way of spending against a cheaper one — rideshare
            against a car, coffee out against brewing at home, ATM fees
            against paying direct. The difference is what you free up.
          </p>
        </div>

        <div className="rounded-xl border border-weave-100 bg-white p-5 space-y-4">
          <Field label="Start from an example">
            <select
              value={preset}
              onChange={(e) => applyPreset(e.target.value)}
              className={INPUT}
            >
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-3">
              <Field label="What you spend on now">
                <input
                  type="text"
                  value={spendLabel}
                  onChange={(e) => setSpendLabel(e.target.value)}
                  placeholder="e.g. Coffee bought out"
                  maxLength={40}
                  className={INPUT}
                />
              </Field>
              <Field label="Its cost per month ($)">
                <input
                  type="number"
                  min={0}
                  step={10}
                  value={spendAmount}
                  onChange={(e) =>
                    setSpendAmount(Math.max(0, Number(e.target.value)))
                  }
                  className={INPUT}
                />
              </Field>
              {cats.length > 0 && (
                <select
                  defaultValue=""
                  onChange={(e) => {
                    const c = cats.find(
                      (x) => x.category === e.target.value
                    );
                    if (c) setSpendAmount(Math.round(c.total / months));
                  }}
                  className="w-full rounded-md border border-weave-200 bg-white px-2 py-1.5 text-xs text-weave-600"
                >
                  <option value="">Fill from my uploaded data…</option>
                  {cats.map((c) => (
                    <option key={c.category} value={c.category}>
                      {c.category} — {usd(c.total / months)}/mo
                    </option>
                  ))}
                </select>
              )}
            </div>
            <div className="space-y-3">
              <Field label="The cheaper way">
                <input
                  type="text"
                  value={altLabel}
                  onChange={(e) => setAltLabel(e.target.value)}
                  placeholder="e.g. Brewing at home"
                  maxLength={40}
                  className={INPUT}
                />
              </Field>
              <Field label="Its cost per month ($)">
                <input
                  type="number"
                  min={0}
                  step={10}
                  value={altAmount}
                  onChange={(e) =>
                    setAltAmount(Math.max(0, Number(e.target.value)))
                  }
                  className={INPUT}
                />
              </Field>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-treasure-200 bg-treasure-50/60 p-5">
          {spendAmount <= 0 ? (
            <p className="text-sm text-weave-600">
              Enter what you spend now to see the comparison.
            </p>
          ) : (
            <>
              <p className="text-sm text-weave-700 leading-relaxed">
                {spendLabel.trim() || "What you spend on now"} costs{" "}
                <span className="font-medium text-weave-900">
                  {usd(spendAmount)}/month
                </span>
                . {altLabel.trim() || "The cheaper way"} costs{" "}
                {usd(altAmount)}/month — a difference of{" "}
                <span
                  className={
                    "font-medium " +
                    (freedMonthly >= 0 ? "text-emerald-700" : "text-red-700")
                  }
                >
                  {freedMonthly >= 0
                    ? `${usd(freedMonthly)}/month freed up`
                    : `${usd(-freedMonthly)}/month more`}
                </span>
                .
              </p>
              {freedMonthly > 0 && (
                <p className="mt-2 text-sm text-weave-600 leading-relaxed">
                  That is{" "}
                  <span className="font-medium text-weave-800">
                    {usd(freedMonthly * 12)}/year
                  </span>{" "}
                  — point it at a goal above and watch it add up.
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium text-weave-700">{label}</label>
      {children}
    </div>
  );
}
