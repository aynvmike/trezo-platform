import { createClient } from "@/lib/supabase/server";
import SleevePanel from "@/components/dashboard/sleeve-panel";

export const dynamic = "force-dynamic";

export default async function SleevesPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="mx-auto max-w-5xl p-6 text-sm text-neutral-400">
        Please sign in to view your capital sleeves.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-100">Capital Sleeves</h1>
        <p className="mt-1 text-sm text-neutral-400">
          How your capital is split by trade horizon, and how much of each sleeve
          is working right now.
        </p>
      </div>
      <SleevePanel userId={user.id} />
    </div>
  );
}
