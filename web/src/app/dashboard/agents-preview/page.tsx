import { redirect } from "next/navigation";

// Agents lives at /dashboard/agents (full layout + actions).
export default function Page() {
  redirect("/dashboard/agents");
}
