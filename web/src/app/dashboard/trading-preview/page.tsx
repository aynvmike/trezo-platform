import { redirect } from "next/navigation";

// Trading lives at /dashboard/paper (full layout + actions).
export default function Page() {
  redirect("/dashboard/paper");
}
