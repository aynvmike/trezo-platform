import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import { AgentsSettings } from "./_agents-settings";

export const dynamic = "force-dynamic";

type Memory = {
  agent: string;
  category: string;
  content: string;
  weight: number;
  updated_at: string;
};

export default async function AgentsSettingsPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/agents");

  const { data: memData } = await supabase
    .from("agent_memory")
    .select("agent, category, content, weight, updated_at")
    .eq("scope", "shared")
    .order("weight", { ascending: false })
    .order("updated_at", { ascending: false })
    .limit(12);
  const learned = (memData ?? []) as Memory[];

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-5xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Settings — Agents
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          The Brain
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">Every agent that runs Trezo — on/off, last tick, and the messages it has produced.</p>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          Trezo&apos;s 17 agents run automatically in the background — Pattern Detection
          every 60 seconds, others on their own cadence. Toggle each on or off here, or
          force an immediate tick with &ldquo;Run now&rdquo;.
        </p>
        <p className="mt-2 max-w-2xl text-sm text-weave-500 leading-relaxed">
          Live agent messages flow into the ticker at the top of every page and the
          full feed on <Link href="/dashboard" className="underline hover:text-weave-800">Overview</Link>.
          Currently in <span className="font-medium text-weave-700">paper-trading mode</span> — every trade is simulated, no real money moves.
        </p>
      </header>

      <AgentsSettings />

      {/* Phase 13 — shared, evolving agent memory */}
      {learned.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="font-serif text-xl text-weave-800">
              What the agents have learned
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-weave-500 leading-relaxed">
              Shared, evolving memory — durable insight the agents keep and build
              on across runs, instead of forgetting it each tick. A heavier
              weight (×) means an observation that has been reinforced over time.
            </p>
          </div>
          <div className="space-y-2">
            {learned.map((m, i) => (
              <div
                key={i}
                className="rounded-xl border border-weave-100 bg-white p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-weave-500">{m.agent}</span>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
                        m.category === "warning"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-weave-50 text-weave-600"
                      )}
                    >
                      {m.category}
                    </span>
                    <span
                      className="text-[10px] text-weave-400"
                      title="Reinforcement weight — how often this has been observed"
                    >
                      ×{Number(m.weight).toFixed(0)}
                    </span>
                  </div>
                </div>
                <p className="mt-1.5 text-sm text-weave-700 leading-relaxed">
                  {m.content}
                </p>
                <p className="mt-1 text-[10px] text-weave-400">
                  {new Date(m.updated_at).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
