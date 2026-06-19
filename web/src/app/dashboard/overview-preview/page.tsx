import { createClient } from "@/lib/supabase/server";
import { OverviewViewRedesign } from "@/components/dashboard/overview-view-redesign";
import { FadeIn } from "@/components/dashboard/fade-in";
import { buildOverviewData } from "@/lib/overview-data";

export const dynamic = "force-dynamic";

export default async function OverviewPreviewPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="mx-auto max-w-6xl p-6 text-sm text-[rgb(var(--muted-foreground))]">
        Please sign in to view the Overview dashboard.
      </div>
    );
  }

  const data = await buildOverviewData(user.id);

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <FadeIn>
        <OverviewViewRedesign data={data} />
      </FadeIn>
    </div>
  );
}
