import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
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
      <PageHeader
        eyebrow="Settings — Ethical Filters"
        title="What Trezo refuses to invest in"
        subtitle="A treasure built on the backs of others isn't a treasure."
        explainer="These toggles control which categories Trezo blocks when you add tickers to a watchlist. The defaults — human rights, OFAC, fraud — are always on and can't be turned off."
      />

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
