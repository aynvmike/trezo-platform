// Live Trading merged into the main Trading page (/dashboard/paper)
// on 2026-05-30 per Mike's review. The TradingModeBanner at the top of
// /dashboard/paper now serves as the single source of truth for
// paper-vs-live state; the go-live checklist moved into a Disclosure
// on the same page.
//
// Keeping this route alive as a permanent redirect so old bookmarks
// and any external links to /dashboard/live still resolve.
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function LiveTradingPage() {
  redirect("/dashboard/paper");
}
