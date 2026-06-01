import { redirect, notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getWatchlist } from "@/lib/watchlists";
import { WatchlistDetail } from "./_detail";

export const dynamic = "force-dynamic";

export default async function WatchlistDetailPage({
  params
}: {
  params: { id: string };
}) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect(`/sign-in?redirect=/dashboard/watchlists/${params.id}`);

  const wl = await getWatchlist(user.id, params.id);
  if (!wl) notFound();

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <WatchlistDetail watchlist={wl.list} initialItems={wl.items} />
    </div>
  );
}
