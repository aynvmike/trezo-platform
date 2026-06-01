import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { BotTuningForm } from "./_bot-form";
import { SettingsAuditPanel } from "@/components/dashboard/settings-audit-panel";
import { LearningInsights } from "@/components/dashboard/learning-insights";
import { TradeImport } from "@/components/dashboard/trade-import";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";

export const dynamic = "force-dynamic";

export default async function BotTuningPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/settings/bot");

  let { data: settings } = await supabase
    .from("bot_settings")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();

  if (!settings) {
    const { data: created } = await supabase
      .from("bot_settings")
      .insert({ user_id: user.id })
      .select("*")
      .single();
    settings = created;
  }

  const liveRequested =
    (process.env.TRADING_MODE ?? "paper").trim().toLowerCase() === "live";

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Settings — Bot Tuning
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          How the bot behaves
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">
          The dials that drive every agent — risk, confidence threshold,
          strategy on/off, autonomy mode. Changes apply within ~30 seconds.
        </p>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          These dials control the agents directly. The Risk Manager reads the
          confidence threshold and position cap; the paper engine reads the
          risk and stop/target percentages. Changes apply within ~30 seconds —
          no restart needed.
        </p>
      </header>

      <div
        className={cn(
          "rounded-xl border p-4 text-sm leading-relaxed",
          liveRequested
            ? "border-amber-200 bg-amber-50 text-amber-900"
            : "border-emerald-200 bg-emerald-50 text-emerald-900"
        )}
      >
        <span className="font-medium">
          Trading mode: {liveRequested ? "LIVE (requested)" : "PAPER"}
        </span>{" "}
        {liveRequested
          ? "Live mode is set in the environment, but real-money execution is not wired yet (Phase 10b) — every trade still runs on paper."
          : "Every trade is simulated — no real money is at risk. Real-money brokerage arrives in Phase 10, behind its own go-live checklist."}
      </div>

      <BotTuningForm
        initial={settings}
        liveEquity={await (async () => {
          try {
            const snap = await fetchAlpacaSnapshot();
            return snap?.configured && snap.account
              ? Number(snap.account.equity)
              : null;
          } catch {
            return null;
          }
        })()}
      />

      <LearningInsights />

      <TradeImport />

      <SettingsAuditPanel />
    </div>
  );
}
