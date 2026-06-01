type Vehicle = {
  title: string;
  tag: string;
  status: string;
  body: string;
};

const VEHICLES: Vehicle[] = [
  {
    title: "Annuities",
    tag: "Long horizon · income",
    status: "Educational",
    body:
      "An annuity is a contract — usually with an insurance company — where you pay in once or over time and the contract pays income back to you later. A fixed-indexed annuity tracks a market index but protects your principal: you keep some upside, you don't lose the floor. It's a retirement-bucket vehicle, not a daily trade."
  },
  {
    title: "Bonds & Bond ETFs",
    tag: "Defensive · income",
    status: "Tracked live via TLT",
    body:
      "Bonds are loans you make to a government or company — they pay interest and return your principal at maturity. Bond ETFs (TLT, IEF, AGG, SHY) bundle many bonds and trade like a stock. They tend to rally when stocks come under stress."
  },
  {
    title: "Income ETFs (REX-style)",
    tag: "Income · capped upside",
    status: "Layer 6 · Dividends",
    body:
      "ETFs like FEPI, NVDY, MSFY, AIPI and YMAX wrap covered-call strategies around big tech or indices and distribute the option income weekly or monthly. Yields can run 8–50% annualised — paid for by capping how much upside you keep on the underlying."
  },
  {
    title: "Futures",
    tag: "Leveraged · same family as Options",
    status: "Coming in a later phase",
    body:
      "Futures are contracts to buy or sell something at a set price on a future date — indices (ES, NQ), commodities (gold, oil), currencies. They share their DNA with the Options Engine but use a different broker class than stocks."
  },
  {
    title: "ETF Rebalancing",
    tag: "Rotation · within a theme",
    status: "Wiring next",
    body:
      "When a single holding inside an ETF is dragging it down, the bot can rotate into a stronger stock from the same ETF — keeping the sector but switching to a stronger horse."
  },
  {
    title: "Forex & cross-asset hedges",
    tag: "Risk-asset family",
    status: "Tracked live via UUP",
    body:
      "Forex and crypto sit in the same risk-asset family — when the dollar firms, both often weaken. Gold and the dollar usually pull against each other. Market Horizons on the Paper Trading page tracks the dollar (UUP)."
  }
];

export function InvestmentVehicles() {
  return (
    <details className="rounded-xl border border-weave-100 bg-white p-5">
      <summary className="cursor-pointer font-serif text-lg text-weave-800">
        Investment vehicles to know (annuities, bonds, futures, REX-style ETFs)
      </summary>
      <p className="beginner-only mt-2 text-sm text-weave-500 leading-relaxed">
        Some of these Trezo does not trade directly today — they are here
        so you know they exist and can ask the agents about them.
      </p>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {VEHICLES.map((v) => (
          <div
            key={v.title}
            className="rounded-lg border border-weave-100 bg-weave-50/40 p-4 space-y-2"
          >
            <div className="flex items-baseline justify-between gap-2 flex-wrap">
              <h3 className="font-medium text-weave-800">{v.title}</h3>
              <span className="text-[10px] uppercase tracking-widest rounded-full bg-treasure-100 text-treasure-700 px-2 py-0.5">
                {v.status}
              </span>
            </div>
            <p className="text-[11px] uppercase tracking-widest text-weave-500">
              {v.tag}
            </p>
            <p className="text-sm text-weave-600 leading-relaxed">{v.body}</p>
          </div>
        ))}
      </div>
    </details>
  );
}
