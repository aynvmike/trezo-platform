/**
 * Site-wide trading-mode banner. Shows above the agent ticker on every
 * dashboard page so the user is never in doubt about which mode they
 * are running in. Server component — reads the environment directly.
 *
 * Phase 10a safety model: even with TRADING_MODE=live, the agents'
 * live execution gate stays inert until the live executor is wired
 * (Phase 10b). That hard gate lives in agents/app/runtime/trading_mode.py
 * and is intentionally NOT flippable from the web.
 */

const MODE = (process.env.TRADING_MODE ?? "paper").trim().toLowerCase();

export function LiveBanner() {
  if (MODE !== "live") {
    return (
      <div className="bg-treasure-100 border-b border-weave-100 px-4 py-1.5 text-center text-[11px] uppercase tracking-widest text-treasure-800">
        Paper mode · no real money at risk
      </div>
    );
  }
  return (
    <div className="bg-red-600 px-4 py-2 text-center text-xs font-medium text-white">
      LIVE mode requested — real-money orders will route through your
      brokerage when the live executor is enabled. Verify the go-live
      checklist on Settings → Live Trading before you trust this.
    </div>
  );
}
