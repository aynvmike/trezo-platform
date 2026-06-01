"use client";

import { useFormState, useFormStatus } from "react-dom";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { saveProfile, type ProfileFormState } from "./actions";

const STEPS = ["Identity", "Capital", "Discipline", "Tax"] as const;
const initialState: ProfileFormState = { ok: false };

function SubmitButton({ label }: { label: string }) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "Saving…" : label}
    </Button>
  );
}

export function OnboardingForm() {
  const [state, formAction] = useFormState(saveProfile, initialState);
  const [step, setStep] = useState(0);

  function errFor(name: string) {
    return state.fieldErrors?.[name]?.[0];
  }

  return (
    <div className="space-y-8">
      {/* Step indicator */}
      <ol className="flex items-center gap-2">
        {STEPS.map((label, i) => (
          <li key={label} className="flex-1">
            <div
              className={cn(
                "h-1.5 rounded-full",
                i <= step ? "bg-weave-600" : "bg-weave-100"
              )}
            />
            <p
              className={cn(
                "mt-2 text-xs font-medium",
                i === step ? "text-weave-700" : "text-weave-400"
              )}
            >
              {i + 1}. {label}
            </p>
          </li>
        ))}
      </ol>

      <form action={formAction} className="space-y-6">
        {/* Step 1: identity */}
        <section className={cn(step === 0 ? "block" : "hidden", "space-y-4")}>
          <div className="space-y-2">
            <Label htmlFor="display_name">What should Trezo call you?</Label>
            <Input id="display_name" name="display_name" required maxLength={80} placeholder="e.g. Mike" />
            {errFor("display_name") && <p className="text-xs text-red-600">{errFor("display_name")}</p>}
          </div>
        </section>

        {/* Step 2: capital */}
        <section className={cn(step === 1 ? "block" : "hidden", "space-y-4")}>
          <p className="text-sm text-weave-600">
            Trezo never holds your money. These numbers help us right-size every trade.
          </p>
          <div className="space-y-2">
            <Label htmlFor="stock_capital_usd">Stock account size (USD)</Label>
            <Input id="stock_capital_usd" name="stock_capital_usd" type="number" min={0} step="0.01" defaultValue="0" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="crypto_capital_usd">Crypto holdings (USD)</Label>
            <Input id="crypto_capital_usd" name="crypto_capital_usd" type="number" min={0} step="0.01" defaultValue="0" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="options_capital_usd">Options capital (USD)</Label>
            <Input id="options_capital_usd" name="options_capital_usd" type="number" min={0} step="0.01" defaultValue="0" />
          </div>
        </section>

        {/* Step 3: discipline */}
        <section className={cn(step === 2 ? "block" : "hidden", "space-y-4")}>
          <div className="space-y-2">
            <Label htmlFor="risk_tolerance">Risk tolerance</Label>
            <select
              id="risk_tolerance"
              name="risk_tolerance"
              defaultValue="balanced"
              className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
            >
              <option value="conservative">Conservative — patience first</option>
              <option value="balanced">Balanced — measured risk</option>
              <option value="aggressive">Aggressive — bigger swings (still risk-defined)</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="daily_profit_target_usd">Daily profit target (USD)</Label>
            <Input
              id="daily_profit_target_usd"
              name="daily_profit_target_usd"
              type="number"
              min={0}
              step="0.01"
              defaultValue="0"
            />
            <p className="text-xs text-weave-500">
              The Daily Profit Lock saves at least this much before extending the day.
            </p>
          </div>
        </section>

        {/* Step 4: tax */}
        <section className={cn(step === 3 ? "block" : "hidden", "space-y-4")}>
          <div className="space-y-2">
            <Label htmlFor="tax_filing_status">Tax filing status</Label>
            <select
              id="tax_filing_status"
              name="tax_filing_status"
              defaultValue="single"
              className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
            >
              <option value="single">Single</option>
              <option value="married_joint">Married, filing jointly</option>
              <option value="married_separate">Married, filing separately</option>
              <option value="head_of_household">Head of household</option>
            </select>
          </div>

          {/* Tax-strategy fields — all optional, power the Tax Optimizer's advice */}
          <div className="rounded-xl border border-weave-100 bg-weave-50/60 p-4 space-y-4">
            <div>
              <p className="text-sm font-medium text-weave-800">
                Finding your tax savings (optional)
              </p>
              <p className="mt-1 text-xs text-weave-500 leading-relaxed">
                If you have a job with a retirement plan, these let the Tax
                Optimizer show whether you are capturing your full employer
                match — usually the highest-return move available. Leave any
                box blank and Trezo simply skips that part. You can change
                these any time in Profile settings.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="annual_income_usd">Annual income / salary (USD)</Label>
              <Input
                id="annual_income_usd"
                name="annual_income_usd"
                type="number"
                min={0}
                step="0.01"
                defaultValue=""
                placeholder="e.g. 60000"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="retirement_contribution_pct">
                Share of salary you put into your workplace retirement plan (%)
              </Label>
              <Input
                id="retirement_contribution_pct"
                name="retirement_contribution_pct"
                type="number"
                min={0}
                max={100}
                step="0.5"
                defaultValue=""
                placeholder="e.g. 3"
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="employer_match_pct">Employer match rate (%)</Label>
                <Input
                  id="employer_match_pct"
                  name="employer_match_pct"
                  type="number"
                  min={0}
                  max={200}
                  step="1"
                  defaultValue=""
                  placeholder="e.g. 50"
                />
                <p className="text-xs text-weave-500">
                  How much your employer adds per dollar — 50 means 50&cent; on the dollar.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="employer_match_cap_pct">…up to this share of salary (%)</Label>
                <Input
                  id="employer_match_cap_pct"
                  name="employer_match_cap_pct"
                  type="number"
                  min={0}
                  max={100}
                  step="0.5"
                  defaultValue=""
                  placeholder="e.g. 6"
                />
                <p className="text-xs text-weave-500">
                  The match usually stops once you contribute this much.
                </p>
              </div>
            </div>
          </div>

          <p className="text-xs text-weave-500">
            Trezo is not your tax advisor — this keeps the Tax Optimizer in
            the right bracket and shows you the math, not personalized advice.
          </p>
        </section>

        {state.error && (
          <p className="text-sm text-red-600" role="alert">{state.error}</p>
        )}

        <div className="flex items-center justify-between pt-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button type="button" onClick={() => setStep((s) => s + 1)}>
              Next
            </Button>
          ) : (
            <SubmitButton label="Finish setup" />
          )}
        </div>
      </form>
    </div>
  );
}
