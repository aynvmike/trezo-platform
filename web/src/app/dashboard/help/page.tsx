import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { HelpContent } from "./_help-content";
import { InvestmentVehicles } from "@/components/help/investment-vehicles";

export const dynamic = "force-dynamic";

export default async function HelpPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/help");

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Help &amp; FAQ
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Quick answers
        </h1>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          Short, plain-language answers about how Trezo works — search, or
          browse by topic. This is the place to look things up, so the rest of
          the app can stay uncluttered.
        </p>
      </header>

      <HelpContent />

      <InvestmentVehicles />
    </div>
  );
}
