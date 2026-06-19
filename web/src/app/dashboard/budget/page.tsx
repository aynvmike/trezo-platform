import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { createClient } from "@/lib/supabase/server";
import { BudgetMirror } from "./_budget-mirror";
import { DataGuide } from "./_data-guide";
import { ProjectionsLab } from "../projections/_projections-lab";

export const dynamic = "force-dynamic";

/**
 * Grasping Wallet — the merged Budget + Projections tab.
 *
 * Mike feedback 2026-05-30: Budget Mirror and Future Projections cover
 * the same arc — today's spending becomes tomorrow's wealth. They
 * belong together. The page tells one story in two sections:
 *
 *   1. "Where money goes" — Budget Mirror. See the leaks.
 *   2. "Where it's headed" — Projections Lab. See what plugging the
 *      leaks compounds into.
 *
 * "Grasping" leans into the gold-building arc — reaching for wealth
 * while holding on tight to what comes in. The wallet motif keeps it
 * grounded; this isn't a fund manager, it's where every dollar gets
 * scrutinised before it's released to grow.
 */
export default async function GraspingWalletPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/budget");

  return (
    <div className="px-4 sm:px-6 py-8 space-y-12 max-w-6xl">
      <PageHeader
        eyebrow="Grasping Wallet"
        title="Hold tight, then let it grow"
        subtitle="See where money goes today, then see where the freed-up dollars land in twenty years."
        explainer="Wealth gets built in two motions: pinch the leaks, then let the rest compound. The first half maps your spending — private, in-browser, never uploaded. The second half projects what the freed-up dollars become in each account type, in real time."
      />

      <section className="space-y-6">
        <div className="border-l-2 border-treasure-500 pl-4">
          <p className="text-[11px] uppercase tracking-widest text-treasure-700">
            Section 1 · Today
          </p>
          <h2 className="font-serif text-2xl text-weave-800 tracking-tight">
            Where money goes
          </h2>
          <p className="mt-1 text-sm text-weave-600 leading-relaxed max-w-2xl">
            A private, in-browser spending analyser. Categorises imports,
            simulates savings, never uploads your file.
          </p>
        </div>
        <BudgetMirror />
        <DataGuide />
      </section>

      <section className="space-y-6">
        <div className="border-l-2 border-treasure-500 pl-4">
          <p className="text-[11px] uppercase tracking-widest text-treasure-700">
            Section 2 · Over the horizon
          </p>
          <h2 className="font-serif text-2xl text-weave-800 tracking-tight">
            Where every account is headed
          </h2>
          <p className="mt-1 text-sm text-weave-600 leading-relaxed max-w-2xl">
            Long-horizon projection across every account type, after tax.
            Flip the &ldquo;What if&rdquo; switches to see how
            tax-loss-harvesting and donating appreciated shares change
            the picture. The math is the same for every account; the
            difference is how taxes eat at the growth.
          </p>
        </div>
        <ProjectionsLab />
        <p className="beginner-only text-xs text-weave-500 leading-relaxed max-w-2xl">
          These are models, not guarantees. Returns are not promised,
          tax rules change, and your situation is yours alone. Use this
          to compare account types — not as personalised tax advice.
          The Tax Optimizer page explains the rules behind each account
          type in plain words.
        </p>
      </section>
    </div>
  );
}
