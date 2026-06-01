import { redirect } from "next/navigation";
// Simulation Lab page consolidated 2026-05-27 into the Strategy Lab tabs.
export default function SimulationRedirect() {
  redirect("/dashboard/strategy-lab?tab=simulation");
}
