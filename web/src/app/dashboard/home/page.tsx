import { redirect } from "next/navigation";

// Overview (classic) folded into the canonical Overview at /dashboard.
export default function Page() {
  redirect("/dashboard");
}
