import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { OverviewViewRedesign } from "@/components/dashboard/overview-view-redesign";
import { FadeIn } from "@/components/dashboard/fade-in";
import { buildOverviewData } from "@/lib/overview-data";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard");

  const data = await buildOverviewData(user.id);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <FadeIn>
        <OverviewViewRedesign data={data} />
      </FadeIn>
    </div>
  );
}
