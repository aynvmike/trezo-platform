import { redirect } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
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
      <PageHeader
        eyebrow="Quick answers"
        title="Help & FAQ"
        subtitle="Short, plain-language answers about how Trezo works — search, or browse by topic, so the rest of the app stays uncluttered."
      />

      <HelpContent />

      <InvestmentVehicles />
    </div>
  );
}
