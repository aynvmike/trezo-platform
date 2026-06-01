import { redirect } from "next/navigation";
// Backtest page consolidated 2026-05-27 into the Strategy Lab tabs.
export default function BacktestRedirect() {
  redirect("/dashboard/strategy-lab?tab=backtest");
}
