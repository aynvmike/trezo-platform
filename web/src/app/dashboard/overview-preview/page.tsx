import { redirect } from "next/navigation";

// Duplicate of the canonical Overview at /dashboard.
export default function Page() {
  redirect("/dashboard");
}
