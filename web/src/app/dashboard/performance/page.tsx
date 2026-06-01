// Performance moved into /dashboard/Overview (Mike feedback 2026-05-28).
// Keeping this route as a permanent redirect so old links / bookmarks
// land on the merged view instead of 404.
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function PerformancePage() {
  redirect("/dashboard");
}
