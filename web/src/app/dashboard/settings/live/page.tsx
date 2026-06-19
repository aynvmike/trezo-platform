import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { OptionsApprovalBadge } from "@/components/dashboard/options-approval-badge";

export const dynamic = "force-dynamic";

/**
 * Live Trading — a quiet status page now, not a wall of checklist.
 *
 * The full go-live checklist still exists (every item is enforced
 * server-side by the agents' live_trading_enabled gate), but it is
 * collapsed behind a Disclosure-style toggle. The headline answers
 * the only question a user actually needs: "is live on?"
 */
export default async function LiveSettingsPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/settings/live");

  const tradingMode = (process.env.TRADING_MODE ?? "paper").trim().toLowerCase();
  const liveRequested = tradingMode === "live";
  // The hard gate lives in agents/app/runtime/trading_mode.py and is
  // intentionally not flippable from the web in Phase 10a.
  const liveExecutorAvailable = false;
  const liveActive = liveRequested && liveExecutorAvailable;

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <PageHeader
        eyebrow="Settings — Live Trading"
        title="Live trading"
        subtitle="Live mode means real-money orders route through your brokerage."
        explainer="Trezo is deliberately paper-only today; the live executor is part of the next phase. This page is where it switches on."
      />

      <section
        className={cn(
          "rounded-xl border p-5",
          liveActive
            ? "border-red-300 bg-red-50"
            : "border-emerald-200 bg-emerald-50"
        )}
      >
        <p
          className={cn(
            "text-base font-medium",
            liveActive ? "text-red-900" : "text-emerald-900"
          )}
        >
          {liveActive
            ? "LIVE — real-money orders are active."
            : "Paper-only — real money is not at risk."}
        </p>
        <p
          className={cn(
            "mt-1 text-sm leading-relaxed",
            liveActive ? "text-red-900" : "text-emerald-900/90"
          )}
        >
          {liveActive
            ? "Every signal that survives the Risk Manager places a real order with your broker. Watch the activity feed."
            : "Live trading is coming. Until the live executor ships and you complete the go-live checklist, every trade is simulated."}
        </p>
      </section>

      <OptionsApprovalBadge />

      <details className="rounded-xl border border-weave-100 bg-white p-5 group">
        <summary className="cursor-pointer list-none flex items-baseline justify-between gap-3">
          <span className="font-medium text-weave-800">
            What it takes to go live
          </span>
          <svg
            className="h-4 w-4 shrink-0 text-weave-400 transition-transform group-open:rotate-180"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>
        <div className="mt-3 space-y-2 text-sm text-weave-600 leading-relaxed">
          <p>
            Live execution is gated behind two independent checks — BOTH
            must hold before any real money moves:
          </p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>
              The environment is set to{" "}
              <code className="text-xs">TRADING_MODE=live</code> on the
              agents service.
            </li>
            <li>
              The code constant{" "}
              <code className="text-xs">_LIVE_EXECUTOR_AVAILABLE</code> is{" "}
              <code className="text-xs">True</code> — flipped on
              deliberately after the live executor lands and is
              reviewed.
            </li>
          </ul>
          <p>
            One gate cannot bypass the other. There is no remote toggle
            by design — flipping it on requires both the env var on
            the host AND the Phase 10b release.
          </p>
          <p className="text-weave-500 text-xs">
            Earlier readiness items (Alpaca live key, Risk Manager
            limits, TCS threshold ≥ 700, 50+ closed paper trades,
            daily-loss limit) are checked by the agents at execute
            time — when something is missing, the activity feed says
            so. You do not need a separate checklist UI; the bot
            refuses to fire if any of these is wrong.
          </p>
          <p>
            Want the long-form checklist back?{" "}
            <Link
              href="/dashboard/agents"
              className="underline hover:text-weave-800"
            >
              The Agents page
            </Link>{" "}
            shows everything the agents verify each tick.
          </p>
        </div>
      </details>
    </div>
  );
}
