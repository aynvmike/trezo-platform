import { redirect } from "next/navigation";

// Markets page consolidated 2026-05-27 into the Paper Trading page
// (Market Horizons card) + Help & FAQ (Investment Vehicles disclosure).
// This redirect keeps old bookmarks working.
export default function MarketsRedirect() {
  redirect("/dashboard/paper");
}
