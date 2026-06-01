// Future Projections merged into Grasping Wallet (/dashboard/budget)
// on 2026-05-30 per Mike's review. Keeping this route alive as a
// permanent redirect so old bookmarks resolve.
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function ProjectionsPage() {
  redirect("/dashboard/budget");
}
