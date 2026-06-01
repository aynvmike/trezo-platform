import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { ProfileForm } from "./_profile-form";
import { DisplayPreferences } from "@/components/dashboard/display-preferences";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";

export const dynamic = "force-dynamic";

export default async function ProfileSettingsPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/settings/profile");

  const { data: profile } = await supabase
    .from("profiles")
    .select(
      "display_name, stock_capital_usd, crypto_capital_usd, options_capital_usd, risk_tolerance, daily_profit_target_usd, daily_loss_limit_usd, tax_filing_status, annual_income_usd, state_tax_rate_pct, retirement_contribution_pct, employer_match_pct, employer_match_cap_pct, withholding_set_aside_pct"
    )
    .eq("user_id", user.id)
    .maybeSingle();

  const alpaca = await fetchAlpacaSnapshot();
  const liveEquity = alpaca?.account ? Number(alpaca.account.equity) : null;
  const liveLabel = alpaca?.venue ? `Alpaca ${alpaca.venue}` : "Alpaca account";

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Settings — Profile
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Your account
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">Capital, discipline rules, and tax filing status. Saved here, read by the agents on their next tick.</p>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          Capital, discipline rules, and tax filing status. Saving an updated daily
          profit target or daily loss limit applies immediately — the agents pick up
          the new values on their next tick.
        </p>
      </header>

      <DisplayPreferences />

      <ProfileForm initial={profile} liveEquity={liveEquity} liveLabel={liveLabel} />
    </div>
  );
}
