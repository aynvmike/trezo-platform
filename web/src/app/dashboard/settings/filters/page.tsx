import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getUserSettings, type EthicalSettings } from "@/lib/services/ethical";
import { FiltersForm } from "./_filters-form";

// Always render fresh — the user just toggled a setting, we never want a cached render
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function FilterSettingsPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/settings/filters");

  const settings: EthicalSettings = await getUserSettings(user.id);

  // Count active exclusions per category for transparency.
  const { data: rows } = await supabase
    .from("ethical_exclusions")
    .select("category")
    .eq("active", true);
  const counts: Record<string, number> = {};
  for (const r of rows ?? []) {
    counts[r.category] = (counts[r.category] ?? 0) + 1;
  }

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Settings — Ethical Filters
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          What Trezo refuses to invest in
        </h1>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          A treasure built on the backs of others isn&apos;t a treasure. These
          toggles control which categories Trezo blocks when you try to add
          tickers to a watchlist. Defaults (human rights, OFAC, fraud) are
          always on — they aren&apos;t shown here because they can&apos;t be
          turned off.
        </p>
      </header>

      <FiltersForm initial={settings} counts={counts} />

      <section className="rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-5 text-sm text-weave-600 leading-relaxed">
        <p className="font-medium text-weave-800">Tier 1 hard-blocks (always on):</p>
        <ul className="mt-2 list-disc list-inside space-y-0.5">
          <li>Companies on the SAM.gov exclusion list</li>
          <li>Active OFAC sanctions</li>
          <li>Adjudicated human-rights violations</li>
          <li>State-sponsored forced-labor supply chains</li>
        </ul>
        <p className="mt-3">
          These can never be overridden, even with a reason. Tier 2 and Tier 3
          (discrimination settlements / SEC fraud) are blocked by default but
          can be overridden with a logged reason from the watchlist screen.
        </p>
      </section>
    </div>
  );
}
