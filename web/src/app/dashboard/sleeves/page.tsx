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
        Please sign in to view your allocation pockets.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-100">Allocation Pockets</h1>
        <p className="mt-1 text-sm text-neutral-400">
          The per-market budgets the agents actually enforce — how much each
          pocket has, and how much of it is working right now.
        </p>
      </div>
      <SleevePanel userId={user.id} />
    </div>
  );
}
