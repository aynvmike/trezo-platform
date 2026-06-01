"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import type { EthicalSettings } from "@/lib/services/ethical";

const CATEGORIES: {
  key: keyof EthicalSettings;
  label: string;
  blurb: string;
  countKey: string;
}[] = [
  { key: "exclude_tobacco",           label: "Tobacco",            blurb: "Cigarette and smokeless tobacco producers.", countKey: "tobacco" },
  { key: "exclude_weapons",           label: "Weapons manufacturers", blurb: "Defense primes and arms makers.",         countKey: "weapons" },
  { key: "exclude_fossil_fuels",      label: "Fossil fuel majors", blurb: "Integrated oil & gas producers.",            countKey: "fossil_fuels" },
  { key: "exclude_private_prisons",   label: "Private prisons",    blurb: "For-profit corrections operators.",          countKey: "private_prisons" },
  { key: "exclude_gambling",          label: "Gambling",           blurb: "Casinos and sportsbooks (default OFF — CZR is a top winner).", countKey: "gambling" },
  { key: "exclude_predatory_lending", label: "Predatory lending",  blurb: "Payday and high-interest consumer lenders.", countKey: "predatory_lending" },
  { key: "exclude_animal_testing",    label: "Animal testing",     blurb: "Cosmetics and beauty companies that test on animals.", countKey: "animal_testing" },
  { key: "exclude_adult_entertainment", label: "Adult entertainment", blurb: "Adult media and live entertainment.",    countKey: "adult_entertainment" },
  { key: "exclude_cannabis",          label: "Cannabis",           blurb: "Cannabis producers (regulatory risk varies).", countKey: "cannabis" },
  { key: "exclude_crypto_mining",     label: "Cryptocurrency mining", blurb: "Bitcoin and crypto miners (energy concerns).", countKey: "crypto_mining" }
];

export function FiltersForm({
  initial,
  counts
}: {
  initial: EthicalSettings;
  counts: Record<string, number>;
}) {
  const router = useRouter();
  const [state, setState] = useState<EthicalSettings>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(key: keyof EthicalSettings) {
    const next = { ...state, [key]: !state[key] };
    setState(next);
    setSaved(false);
    setError(null);
    setSaving(true);
    try {
      const r = await fetch("/api/filter-settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: next[key] }),
        cache: "no-store"
      });
      if (!r.ok) throw new Error("save failed");
      // Use the server's response as the source of truth — sync local state
      // to whatever actually landed in the database.
      const j = (await r.json()) as { settings: EthicalSettings };
      if (j.settings) setState(j.settings);
      // Invalidate the Next.js router cache so the next navigation/refresh
      // re-reads from the server. Fixes the "toggle reverts on refresh" issue.
      router.refresh();
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
      // Revert
      setState((cur) => ({ ...cur, [key]: !next[key] }));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-medium text-weave-800">Optional categories</h2>
        <p className="text-xs text-weave-500">
          {saving ? "Saving…" : saved ? "Saved." : error ? error : "Toggles save automatically"}
        </p>
      </div>
      <ul className="rounded-xl border border-weave-100 bg-white divide-y divide-weave-50">
        {CATEGORIES.map((c) => (
          <li key={c.key} className="flex items-start gap-4 p-4">
            <div className="flex-1">
              <p className="font-medium text-weave-800">
                {c.label}{" "}
                {counts[c.countKey] && (
                  <span className="ml-1 text-[10px] uppercase tracking-widest rounded-full bg-weave-50 text-weave-500 px-2 py-0.5">
                    {counts[c.countKey]} tickers
                  </span>
                )}
              </p>
              <p className="text-sm text-weave-500 leading-relaxed">{c.blurb}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={state[c.key]}
              aria-label={`Toggle ${c.label}`}
              onClick={() => toggle(c.key)}
              className={
                state[c.key]
                  ? "relative h-6 w-11 rounded-full transition bg-weave-600"
                  : "relative h-6 w-11 rounded-full transition bg-weave-200"
              }
            >
              <span
                className={
                  state[c.key]
                    ? "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition translate-x-5"
                    : "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition translate-x-0"
                }
              />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
