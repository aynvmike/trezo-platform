import { redirect } from "next/navigation";
// Pattern Engine page consolidated 2026-05-27 into the Strategy Lab tabs.
// This redirect keeps old bookmarks working.
export default function PatternsRedirect() {
  redirect("/dashboard/strategy-lab?tab=patterns");
}
