"use client";

import { useFormState, useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { saveProfileSettings, type ProfileFormState } from "./_actions";
import { CapitalAllocator } from "@/components/dashboard/capital-allocator";

type Profile = {
  display_name: string | null;
  stock_capital_usd: number | null;
  crypto_capital_usd: number | null;
  options_capital_usd: number | null;
  risk_tolerance: string | null;
  daily_profit_target_usd: number | null;
  daily_loss_limit_usd: number | null;
  tax_filing_status: string | null;
  annual_income_usd: number | null;
  state_tax_rate_pct: number | null;
  retirement_contribution_pct: number | null;
  employer_match_pct: number | null;
  employer_match_cap_pct: number | null;
  withholding_set_aside_pct: number | null;
} | null;

const initial: ProfileFormState = { ok: false };

function SaveButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "Saving…" : "Save changes"}
    </Button>
  );
}

export function ProfileForm({
  initial: profile,
  liveEquity = null,
  liveLabel = "Alpaca account"
}: {
  initial: Profile;
  liveEquity?: number | null;
  liveLabel?: string;
}) {
  const [state, formAction] = useFormState(saveProfileSettings, initial);

  function err(name: string) {
    return state.fieldErrors?.[name]?.[0];
  }

  return (
    <form action={formAction} className="space-y-8">
      {/* Identity */}
      <section className="space-y-4">
        <h2 className="font-medium text-weave-800">Identity</h2>
        <div className="space-y-2">
          <Label htmlFor="display_name">Display name</Label>
          <Input
            id="display_name"
            name="display_name"
            defaultValue={profile?.display_name ?? ""}
            maxLength={80}
            required
          />
          {err("display_name") && <p className="text-xs text-red-600">{err("display_name")}</p>}
        </div>
      </section>

      {/* Capital — broker-aware, with manual-dollar or total+split modes. */}
      <CapitalAllocator
        initialStock={Number(profile?.stock_capital_usd ?? 0)}
        initialCrypto={Number(profile?.crypto_capital_usd ?? 0)}
        initialOptions={Number(profile?.options_capital_usd ?? 0)}
        liveEquity={liveEquity}
        liveLabel={liveLabel}
      />

      {/* Discipline */}
      <section className="space-y-4">
        <h2 className="font-medium text-weave-800">Discipline rules</h2>

        <div className="space-y-2">
          <Label htmlFor="risk_tolerance">Risk tolerance</Label>
          <select
            id="risk_tolerance"
            name="risk_tolerance"
            defaultValue={profile?.risk_tolerance ?? "balanced"}
            className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
          >
            <option value="conservative">Conservative — patience first</option>
            <option value="balanced">Balanced — measured risk</option>
            <option value="aggressive">Aggressive — bigger swings</option>
          </select>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="daily_profit_target_usd">Daily profit target (USD)</Label>
            <Input
              id="daily_profit_target_usd"
              name="daily_profit_target_usd"
              type="number"
              min={0}
              step="0.01"
              defaultValue={profile?.daily_profit_target_usd ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              When today&apos;s realized P&amp;L reaches this, the bot auto-locks the
              target into your vault. Vaulted money can&apos;t be re-traded.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="daily_loss_limit_usd">Daily loss limit (USD)</Label>
            <Input
              id="daily_loss_limit_usd"
              name="daily_loss_limit_usd"
              type="number"
              min={0}
              step="0.01"
              defaultValue={profile?.daily_loss_limit_usd ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              If today&apos;s realized losses reach this, the Risk Manager vetoes
              every new signal for the rest of the day. Set to 0 to disable.
            </p>
          </div>
        </div>
      </section>

      {/* Tax */}
      <section className="space-y-4">
        <h2 className="font-medium text-weave-800">Tax</h2>
        <p className="text-sm text-weave-500">
          These feed the Tax Optimizer — its estimate of what you owe, and the
          Tax Strategy section that shows your employer-match math. Trezo
          isn&apos;t your tax advisor; this just keeps the numbers honest.
        </p>

        <div className="grid sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="tax_filing_status">Tax filing status</Label>
            <select
              id="tax_filing_status"
              name="tax_filing_status"
              defaultValue={profile?.tax_filing_status ?? "single"}
              className="flex h-10 w-full rounded-md border border-weave-200 bg-white px-3 py-2 text-sm text-weave-800 focus:outline-none focus:ring-2 focus:ring-weave-500"
            >
              <option value="single">Single</option>
              <option value="married_joint">Married, filing jointly</option>
              <option value="married_separate">Married, filing separately</option>
              <option value="head_of_household">Head of household</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="annual_income_usd">Annual income / salary (USD)</Label>
            <Input
              id="annual_income_usd"
              name="annual_income_usd"
              type="number"
              min={0}
              step="0.01"
              defaultValue={profile?.annual_income_usd ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              Short-term gains stack on top of this — and it sizes the
              employer-match math.
            </p>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="state_tax_rate_pct">State tax rate (%)</Label>
            <Input
              id="state_tax_rate_pct"
              name="state_tax_rate_pct"
              type="number"
              min={0}
              max={20}
              step="0.1"
              defaultValue={profile?.state_tax_rate_pct ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              Your state&apos;s income-tax rate. Set to 0 for a no-income-tax state.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="retirement_contribution_pct">
              Retirement plan contribution (% of salary)
            </Label>
            <Input
              id="retirement_contribution_pct"
              name="retirement_contribution_pct"
              type="number"
              min={0}
              max={100}
              step="0.5"
              defaultValue={profile?.retirement_contribution_pct ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              How much of your pay goes into a workplace 401(k) / 403(b).
            </p>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="employer_match_pct">Employer match rate (%)</Label>
            <Input
              id="employer_match_pct"
              name="employer_match_pct"
              type="number"
              min={0}
              max={200}
              step="1"
              defaultValue={profile?.employer_match_pct ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              What your employer adds per dollar — 50 means 50&cent; on the dollar.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="employer_match_cap_pct">
              Match cap (% of salary)
            </Label>
            <Input
              id="employer_match_cap_pct"
              name="employer_match_cap_pct"
              type="number"
              min={0}
              max={100}
              step="0.5"
              defaultValue={profile?.employer_match_cap_pct ?? 0}
              required
            />
            <p className="text-xs text-weave-500">
              The match usually stops once you contribute this much of your salary.
            </p>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="withholding_set_aside_pct">
              Tax set-aside on trading gains (%)
            </Label>
            <Input
              id="withholding_set_aside_pct"
              name="withholding_set_aside_pct"
              type="number"
              min={0}
              max={100}
              step="1"
              defaultValue={profile?.withholding_set_aside_pct ?? 25}
              required
            />
            <p className="text-xs text-weave-500">
              The share of trading gains the Tax page suggests setting aside —
              a common rule of thumb is 25%.
            </p>
          </div>
        </div>
      </section>

      {state.message && (
        <p className={state.ok ? "text-sm text-emerald-700" : "text-sm text-red-600"}>
          {state.message}
        </p>
      )}

      <div className="flex justify-end">
        <SaveButton />
      </div>
    </form>
  );
}
