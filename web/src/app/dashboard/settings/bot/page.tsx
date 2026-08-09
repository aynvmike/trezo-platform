import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { BotTuningForm } from "./_bot-form";
import { SettingsAuditPanel } from "@/components/dashboard/settings-audit-panel";
import { LearningInsights } from "@/components/dashboard/learning-insights";
import { TradeImport } from "@/components/dashboard/trade-import";
import { fetchAlpacaSnapshot } from "@/lib/alpaca-snapshot";
import { AccountSwitcher, type BookOption } from "./_account-switcher";

export const dynamic = "force-dynamic";

export default async function BotTuningPage({
  searchParams
}: {
  searchParams?: { account?: string };
}) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/settings/bot");

  // A person can own several BOOKS (2026-08-09). These dials belong to a
  // book, not to the person, so resolve which book is being edited before
  // reading anything. RLS on trading_accounts already limits rows to
  // owner_id = auth.uid(), so this cannot surface someone else's account.
  const { data: accountRows } = await supabase
    .from("trading_accounts")
    .select("account_key, label, is_paper")
    .eq("owner_id", user.id)
    .eq("is_active", true)
    .order("label");

  const { data: capitalRows } = await supabase
    .from("paper_accounts")
    .select("user_id, starting_capital_usd");

  const capitalByKey = new Map<string, number | null>(
    (capitalRows ?? []).map((r) => [
      String(r.user_id),
      r.starting_capital_usd === null ? null : Number(r.starting_capital_usd)
    ])
  );

  const books: BookOption[] = (accountRows ?? []).map((r) => ({
    account_key: String(r.account_key),
    label: r.label,
    is_paper: Boolean(r.is_paper),
    starting_capital_usd: capitalByKey.get(String(r.account_key)) ?? null
  }));

  // Requested book must be one of the caller's own. Anything else falls
  // back to their own key rather than erroring -- a stale bookmark should
  // land somewhere sane, not on a stranger's settings.
  const requested = searchParams?.account;
  const activeKey =
    requested && books.some((b) => b.account_key === requested)
      ? requested
      : books.some((b) => b.account_key === user.id)
        ? user.id
        : (books[0]?.account_key ?? user.id);

  let { data: settings } = await supabase
    .from("bot_settings")
    .select("*")
    .eq("user_id", activeKey)
    .maybeSingle();

  if (!settings) {
    const { data: created } = await supabase
      .from("bot_settings")
      .insert({ user_id: activeKey })
      .select("*")
      .single();
    settings = created;
  }

  const activeBook = books.find((b) => b.account_key === activeKey) ?? null;

  const liveRequested =
    (process.env.TRADING_MODE ?? "paper").trim().toLowerCase() === "live";

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <PageHeader
        eyebrow="Settings — Bot Tuning"
        title="How the bot behaves"
        subtitle="The dials that drive every agent — risk, confidence threshold, strategy on/off, autonomy mode. Changes apply within ~30 seconds."
        explainer="These dials control the agents directly. The Risk Manager reads the confidence threshold and position cap; the paper engine reads the risk and stop/target percentages — no restart needed."
      />

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

      <AccountSwitcher books={books} activeKey={activeKey} />

      <BotTuningForm
        key={activeKey}
        accountKey={activeKey}
        accountLabel={activeBook?.label ?? null}
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
