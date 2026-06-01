import { cn } from "@/lib/utils";

/**
 * Trading mode banner - the big, unmistakable indicator that Mike
 * asked for. Single source of truth: agents-side TRADING_MODE env
 * var + the Phase 10b gate. Until the live executor lands and is
 * deliberately flipped on, every trade is paper - so the banner
 * stays green even when TRADING_MODE=live is "requested."
 *
 * Three possible states:
 *   PAPER          green   TRADING_MODE!=live (the safe default)
 *   LIVE-REQUESTED amber   TRADING_MODE=live but executor not on yet
 *   LIVE-ACTIVE    red     TRADING_MODE=live AND executor switched on
 *
 * Phase 10a ships the first two. LIVE-ACTIVE waits on Phase 10b.
 */
export function TradingModeBanner({
  autoTradeEnabled = true,
}: {
  autoTradeEnabled?: boolean;
} = {}) {
  const liveRequested =
    (process.env.TRADING_MODE ?? "paper").trim().toLowerCase() === "live";
  // The hard gate is enforced server-side in
  // agents/app/runtime/trading_mode.py - intentionally not flippable
  // from the web in Phase 10a.
  const liveExecutorAvailable = false;
  const liveActive = liveRequested && liveExecutorAvailable;

  const state: "paper" | "live-requested" | "live-active" = liveActive
    ? "live-active"
    : liveRequested
      ? "live-requested"
      : "paper";

  const headline =
    state === "live-active"
      ? "LIVE MODE"
      : state === "live-requested"
        ? "PAPER MODE"
        : "PAPER MODE";

  const subhead =
    state === "live-active"
      ? "Real money at risk · every order routes to your broker"
      : state === "live-requested"
        ? "Live requested — executor not on yet · trades still paper"
        : "No real money at risk · simulated against live prices";

  const tone =
    state === "live-active"
      ? "border-red-400 bg-red-50 text-red-900"
      : state === "live-requested"
        ? "border-amber-300 bg-amber-50 text-amber-900"
        : "border-emerald-300 bg-emerald-50 text-emerald-900";

  const dotTone =
    state === "live-active"
      ? "bg-red-500"
      : state === "live-requested"
        ? "bg-amber-500"
        : "bg-emerald-500";

  return (
    <div
      className={cn(
        "rounded-xl border-2 p-5 flex items-center justify-between gap-4 flex-wrap",
        tone
      )}
      role="status"
    >
      <div className="flex items-center gap-4">
        <span
          className={cn(
            "h-3 w-3 rounded-full shrink-0",
            dotTone,
            state === "live-active" && "animate-pulse"
          )}
          aria-hidden="true"
        />
        <div>
          <p className="font-serif text-3xl tracking-tight font-medium">
            {headline}
          </p>
          <p className="text-sm leading-relaxed opacity-80">{subhead}</p>
        </div>
      </div>
      <div className="text-right space-y-1">
        <p className="font-mono text-sm font-medium">
          Auto-trade: {autoTradeEnabled ? "ON" : "OFF"}
        </p>
        <p className="font-mono text-[10px] opacity-70">
          TRADING_MODE={liveRequested ? "live" : "paper"} · executor=
          {liveExecutorAvailable ? "available" : "off"}
        </p>
        {!autoTradeEnabled ? (
          <p className="text-[11px] opacity-80 italic">
            Signals + learning still on. No trades placed.
          </p>
        ) : null}
      </div>
    </div>
  );
}
