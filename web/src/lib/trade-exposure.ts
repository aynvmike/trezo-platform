/** Market exposure is distinct from buying (long) or writing (short) a contract. */
export function optionExposure(strategy: string, symbol = "", side = "long"): string {
  const name = strategy.toLowerCase();
  if (["bear_call_spread", "bear_put_spread"].includes(name)) return "Bearish";
  if (["bull_put_spread", "bull_call_spread"].includes(name)) return "Bullish";
  if (["wheel_csp", "cash_secured_put"].includes(name)) return "Neutral / bullish · written put";
  if (["wheel_cc", "covered_call"].includes(name)) return "Neutral / bullish · capped upside";
  if (name === "iron_condor" || name === "butterfly") return "Range-bound";
  const contractType = /\d{6}([CP])\d{8}$/.exec(symbol.toUpperCase())?.[1];
  const put = name === "long_put" || name === "short_put" || contractType === "P";
  const call = name === "long_call" || name === "short_call" || contractType === "C";
  if (!put && !call) return "Option direction unverified";
  const written = side.toLowerCase() === "short" || name.startsWith("short_");
  const bearish = put ? !written : written;
  return `${bearish ? "Bearish" : "Bullish"} · ${written ? "written" : "purchased"} ${put ? "put" : "call"}`;
}
