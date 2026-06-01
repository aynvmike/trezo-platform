import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import {
  STRATEGY_LIBRARY,
  REGIME_PLAYBOOK,
  REGIME_LABEL
} from "@/lib/strategy-library";
import { resolveSuggestion } from "./_actions";

import { Disclosure } from "@/components/ui/disclosure";
import { StrategyProposalsFeed } from "@/components/dashboard/strategy-proposals";

export const dynamic = "force-dynamic";

const FAMILY_LABEL: Record<string, string> = {
  trend: "Trend", momentum: "Momentum", mean_reversion: "Mean reversion",
  breakout: "Breakout", income: "Income", event_driven: "Event-driven",
  volatility: "Volatility", rotation: "Rotation", arbitrage: "Arbitrage"
};

const SEVERITY_COLOR: Record<string, string> = {
  high: "bg-red-100 text-red-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-weave-100 text-weave-700"
};

const STATUS_COLOR: Record<string, string> = {
  applied: "bg-emerald-100 text-emerald-800",
  suggested: "bg-amber-100 text-amber-800",
  expired: "bg-weave-50 text-weave-500",
  dismissed: "bg-weave-50 text-weave-500"
};

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "text-emerald-700",
  negative: "text-red-600",
  neutral: "text-weave-500"
};

const AUTONOMY_LABEL: Record<string, string> = {
  suggest: "Suggest only",
  guarded: "Guarded auto",
  full: "Full auto"
};

const RISK_COLOR: Record<string, string> = {
  conservative: "bg-emerald-100 text-emerald-800",
  moderate: "bg-amber-100 text-amber-800",
  aggressive: "bg-red-100 text-red-800"
};

function timeAgo(iso: string): string {
  const d = new Date(iso).getTime();
  if (!d) return "—";
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export default async function StrategyPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/strategy");

  const [postureRes, logRes, eventRes, settingsRes] = await Promise.all([
    supabase
      .from("strategy_scope_adjustments")
      .select("*")
      .eq("action", "set_posture")
      .order("created_at", { ascending: false })
      .limit(1),
    supabase
      .from("strategy_scope_adjustments")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(25),
    supabase
      .from("agent_messages")
      .select("id, created_at, payload")
      .eq("kind", "event")
      .order("created_at", { ascending: false })
      .limit(20),
    supabase
      .from("bot_settings")
      .select("autonomy_mode")
      .eq("user_id", user.id)
      .maybeSingle()
  ]);

  const posture = (postureRes.data ?? [])[0] ?? null;
  const log = logRes.data ?? [];
  const events = eventRes.data ?? [];
  const autonomy = String(settingsRes.data?.autonomy_mode ?? "guarded");

  const regime: string | null =
    posture?.trigger && String(posture.trigger).startsWith("regime:")
      ? String(posture.trigger).slice("regime:".length)
      : null;
  const play = regime ? REGIME_PLAYBOOK[regime] : null;

  const byFamily = new Map<string, typeof STRATEGY_LIBRARY>();
  for (const c of STRATEGY_LIBRARY) {
    const arr = byFamily.get(c.family) ?? [];
    arr.push(c);
    byFamily.set(c.family, arr);
  }

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Settings — Strategy Engine
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Strategy Engine &amp; Adaptive Scope
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">
          The page where the bot tells you which strategies it wants to
          favour, trim, or pause — and when it wants to change its mind.
        </p>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          Trezo carries a library of proven strategies the agents reason
          over, and an Adaptive Scope engine that reads the market regime
          and breaking news, then adjusts how the bot trades — tightening
          stops, raising the confidence bar, pausing a strategy, or
          flagging a ticker — without you having to track any of it by
          hand.
        </p>
      </header>

      {/* Current posture */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">Current posture</h2>
        <div className="rounded-xl border border-weave-100 bg-white p-5">
          {posture ? (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-[11px] uppercase tracking-widest rounded-full px-2.5 py-1 bg-weave-100 text-weave-800">
                  {regime ? REGIME_LABEL[regime] ?? regime : "—"}
                </span>
                <span className="text-[11px] uppercase tracking-widest rounded-full px-2.5 py-1 bg-treasure-200 text-treasure-800">
                  Autonomy: {AUTONOMY_LABEL[autonomy] ?? autonomy}
                </span>
                <span className="text-xs text-weave-500">
                  set {timeAgo(posture.created_at)}
                </span>
              </div>
              <p className="mt-3 text-sm text-weave-600 leading-relaxed">
                {posture.reason}
              </p>
              <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
                <Stat label="Stop distance" value={`x${Number(posture.stop_multiplier).toFixed(2)}`} />
                <Stat label="Confidence bar" value={`+${posture.tcs_bump} TCS`} />
                <Stat
                  label="Strategies paused"
                  value={String((posture.paused_strategies ?? []).length)}
                />
              </div>
              {(posture.paused_strategies ?? []).length > 0 && (
                <p className="mt-3 text-xs text-weave-500">
                  Paused: {(posture.paused_strategies as string[]).join(", ")}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-weave-500">
              No posture set yet. The Adaptive Scope agent reads the market
              regime every 10 minutes and sets one. Apply migration 0013 and
              restart the agents if this stays empty.
            </p>
          )}
        </div>
      </section>

      <StrategyProposalsFeed userId={user.id} />

      {/* Regime playbook */}
      {play && (
        <section>
          <h2 className="font-serif text-xl text-weave-800 mb-3">
            Regime playbook
          </h2>
          <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-600 leading-relaxed">
            <p className="mb-3">{play.summary}</p>
            <div className="grid sm:grid-cols-3 gap-3">
              <PlayCol label="Favor" tone="good" families={play.favor} />
              <PlayCol label="Trade smaller" tone="warn" families={play.reduce} />
              <PlayCol label="Pause" tone="bad" families={play.pause} />
            </div>
          </div>
        </section>
      )}

      {/* Scope adjustment log */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Scope adjustment log{" "}
          <span className="text-sm text-weave-500">({log.length})</span>
        </h2>
        {log.length === 0 ? (
          <EmptyCard>
            No scope adjustments recorded yet. Every regime posture and
            ticker flag the engine makes is logged here.
          </EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[720px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">When</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Scope</th>
                  <th className="px-4 py-3">Reason</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right"></th>
                </tr>
              </thead>
              <tbody>
                {log.map((r) => (
                  <tr key={r.id} className="border-b border-weave-50 last:border-0">
                    <td className="px-4 py-3 text-xs text-weave-500 whitespace-nowrap">
                      {timeAgo(r.created_at)}
                    </td>
                    <td className="px-4 py-3 text-weave-700">
                      {String(r.action).replace(/_/g, " ")}
                    </td>
                    <td className="px-4 py-3 font-mono text-weave-800">{r.scope}</td>
                    <td className="px-4 py-3 text-weave-600 max-w-md">{r.reason}</td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                        SEVERITY_COLOR[r.severity] ?? "bg-weave-50 text-weave-500"
                      )}>
                        {r.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                        STATUS_COLOR[r.status] ?? "bg-weave-50 text-weave-500"
                      )}>
                        {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {r.status === "suggested" ? (
                        <div className="flex justify-end gap-2">
                          <form action={resolveSuggestion}>
                            <input type="hidden" name="row_id" value={r.id} />
                            <input type="hidden" name="decision" value="apply" />
                            <button
                              type="submit"
                              className="text-xs rounded-md border border-emerald-300 px-2.5 py-1 text-emerald-700 hover:bg-emerald-50"
                            >
                              Approve
                            </button>
                          </form>
                          <form action={resolveSuggestion}>
                            <input type="hidden" name="row_id" value={r.id} />
                            <input type="hidden" name="decision" value="dismiss" />
                            <button
                              type="submit"
                              className="text-xs rounded-md border border-weave-300 px-2.5 py-1 text-weave-600 hover:bg-weave-50"
                            >
                              Dismiss
                            </button>
                          </form>
                        </div>
                      ) : (
                        <span className="text-xs text-weave-300">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Detected events */}
      <section>
        <h2 className="font-serif text-xl text-weave-800 mb-3">
          Detected events{" "}
          <span className="text-sm text-weave-500">({events.length})</span>
        </h2>
        {events.length === 0 ? (
          <EmptyCard>
            No market events detected yet. The Market Sentiment and Research
            agents post earnings, M&amp;A, guidance, and other events here.
          </EmptyCard>
        ) : (
          <div className="rounded-xl border border-weave-100 bg-white overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[720px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-widest text-weave-500 border-b border-weave-100">
                  <th className="px-4 py-3">When</th>
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Event</th>
                  <th className="px-4 py-3">Headline</th>
                  <th className="px-4 py-3">Sentiment</th>
                  <th className="px-4 py-3">Severity</th>
                </tr>
              </thead>
              <tbody>
                {events.map((m) => {
                  const p = m.payload ?? {};
                  const sentiment = String(p.sentiment ?? "neutral");
                  return (
                    <tr key={m.id} className="border-b border-weave-50 last:border-0">
                      <td className="px-4 py-3 text-xs text-weave-500 whitespace-nowrap">
                        {timeAgo(m.created_at)}
                      </td>
                      <td className="px-4 py-3 font-mono font-medium text-weave-800">
                        {p.ticker ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-weave-600">
                        {String(p.event_type ?? "general").replace(/_/g, " ")}
                      </td>
                      <td className="px-4 py-3 text-weave-600 max-w-md">
                        {p.headline ?? "—"}
                      </td>
                      <td className={cn(
                        "px-4 py-3 capitalize",
                        SENTIMENT_COLOR[sentiment] ?? "text-weave-500"
                      )}>
                        {sentiment}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn(
                          "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                          SEVERITY_COLOR[String(p.severity ?? "low")] ?? "bg-weave-50 text-weave-500"
                        )}>
                          {p.severity ?? "low"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Strategy library — collapsed; each family is a horizontal carousel */}
      <Disclosure
        title={`Strategy library (${STRATEGY_LIBRARY.length})`}
        hint="swipe each family sideways"
      >
        <p className="text-weave-500 mb-4">
          The proven strategies the agents reason over. The Adaptive Scope
          engine favors or pauses whole families as the regime shifts.
        </p>
        <div className="space-y-5">
          {[...byFamily.entries()].map(([family, cards]) => (
            <div key={family}>
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-[11px] uppercase tracking-widest text-treasure-600 mb-2">
                  {FAMILY_LABEL[family] ?? family}
                </h3>
                <span className="text-[11px] text-weave-400">
                  {cards.length} {cards.length === 1 ? "strategy" : "strategies"} · swipe →
                </span>
              </div>
              {/* Horizontal carousel — one swipe strip per family, instead
                  of a long vertical scroll. */}
              <div className="flex gap-3 overflow-x-auto snap-x pb-2 -mx-1 px-1">
                {cards.map((c) => (
                  <div
                    key={c.id}
                    className="snap-start shrink-0 w-72 rounded-xl border border-weave-100 bg-white p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-medium text-weave-800">{c.name}</p>
                      <span className={cn(
                        "shrink-0 text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                        RISK_COLOR[c.riskProfile] ?? "bg-weave-50 text-weave-500"
                      )}>
                        {c.riskProfile}
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm text-weave-600 leading-relaxed">
                      {c.thesis}
                    </p>
                    <p className="mt-2 text-xs text-weave-500">
                      Best in: {c.bestRegimes.map((r) => REGIME_LABEL[r] ?? r).join(", ")}
                      {c.trezoLayer ? ` · Layer ${c.trezoLayer}` : ""}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Disclosure>

      <Disclosure title="How Adaptive Scope works">
        <p>
          The Adaptive Scope engine only ever makes risk-<span className="font-medium text-weave-800">reducing</span> moves —
          it can tighten stops, raise the confidence bar, pause a strategy, or
          flag a ticker, but never loosen risk past your baseline. How much it
          may do on its own is set by the autonomy mode on the{" "}
          <span className="font-medium text-weave-800">Bot Tuning</span> page.
        </p>
      </Disclosure>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-weave-100 bg-treasure-50/50 p-3">
      <p className="text-[11px] uppercase tracking-widest text-weave-500">{label}</p>
      <p className="mt-1 font-mono text-lg font-medium text-weave-800">{value}</p>
    </div>
  );
}

function PlayCol({
  label,
  tone,
  families
}: {
  label: string;
  tone: "good" | "warn" | "bad";
  families: string[];
}) {
  const toneClass =
    tone === "good" ? "text-emerald-700"
    : tone === "warn" ? "text-amber-700"
    : "text-red-600";
  return (
    <div>
      <p className={cn("text-[11px] uppercase tracking-widest font-medium", toneClass)}>
        {label}
      </p>
      <p className="mt-1 text-weave-700 capitalize">
        {families.length ? families.join(", ").replace(/_/g, " ") : "—"}
      </p>
    </div>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center">
      {children}
    </div>
  );
}
