interface Layer {
  num: number;
  name: string;
  blurb: string;
  ring: "outer" | "mid" | "inner";
}

/**
 * Layer cards on the landing page. Order + color match the ProtectiveRings
 * atom: Layer 1 (outermost, most volatile) → Layer 7 (innermost treasure).
 * Each card is tinted with its shell's exact gold shade so the section reads
 * as a continuation of the rings, ending on the featured treasure core.
 */
const LAYERS: Layer[] = [
  { num: 1, name: "Crypto Bot",         ring: "outer", blurb: "24/7 trading of XRP, ETH, SOL — patient, rules-based. Takes the market's weather first." },
  { num: 2, name: "Stock Bot (STMS)",   ring: "outer", blurb: "7–11 AM small-cap momentum, with hard stops and time-bound exits." },
  { num: 3, name: "Options Engine",     ring: "outer", blurb: "Pattern-driven, multi-strategy, risk-defined per trade." },
  { num: 4, name: "Extended Strategy",  ring: "mid",   blurb: "Swing trades, penny stocks, event-driven plays — longer-held but still active." },
  { num: 5, name: "Dividend Wheel",     ring: "mid",   blurb: "Covered calls and cash-secured puts on quality names you already hold." },
  { num: 6, name: "Dividends",          ring: "inner", blurb: "Passive income — YieldMax + blue chip — money sits and pays you weekly or quarterly." },
  { num: 7, name: "KINDRIP",            ring: "inner", blurb: "Children's portfolio. The innermost vault — the treasure the rest is built to protect." }
];

// Gold shades matching the ProtectiveRings shells (outer → inner).
const SHADE = ["#3a3630", "#4c4231", "#6a5530", "#8a6c2e", "#a8843a", "#bc9042", "#c4964a"];

export function SevenLayers() {
  const core = LAYERS[6];
  const rest = LAYERS.slice(0, 6);
  return (
    <section className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
      <div className="text-center mb-12">
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          The Woven Basket
        </p>
        <h2 className="mt-2 font-serif text-3xl sm:text-4xl text-weave-800 tracking-tight">
          Seven Layers. One Treasure.
        </h2>
        <p className="mt-4 max-w-2xl mx-auto text-weave-600 leading-relaxed">
          From the outer shell (where the market hits hardest) inward to the
          vault (where your kids&apos; future lives), each layer protects the
          ones beneath it — one system, in constant motion.
        </p>
      </div>

      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rest.map((layer) => {
          const shade = SHADE[layer.num - 1];
          return (
            <li
              key={layer.num}
              className="group relative rounded-xl border p-5 transition duration-200 hover:-translate-y-0.5 depth-raised"
              style={{ borderColor: `${shade}66`, background: "rgb(var(--surface))" }}
            >
              <span
                className="pointer-events-none absolute inset-x-0 top-0 h-px rounded-t-xl"
                style={{ background: `linear-gradient(90deg, transparent, ${shade}, transparent)` }}
              />
              <div className="flex items-center gap-3">
                <span
                  className="grid h-9 w-9 place-items-center rounded-full font-serif text-[15px]"
                  style={{ background: shade, color: "#fbf3e2" }}
                >
                  {layer.num}
                </span>
                <h3 className="font-medium text-weave-800">{layer.name}</h3>
              </div>
              <p className="mt-3 text-sm text-weave-600 leading-relaxed">
                {layer.blurb}
              </p>
              <span className="absolute top-3 right-3 text-[10px] uppercase tracking-widest text-weave-400">
                {layer.ring} ring
              </span>
            </li>
          );
        })}
      </ol>

      {/* The treasure — KINDRIP, the core every other layer protects. */}
      <div
        className="mt-4 relative overflow-hidden rounded-2xl border p-6 sm:p-8 depth-raised"
        style={{ borderColor: "#c4964a66", background: "linear-gradient(135deg, rgba(196,150,74,0.16) 0%, rgba(196,150,74,0.03) 55%, transparent 100%)" }}
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <span
            className="grid h-14 w-14 shrink-0 place-items-center rounded-full font-serif text-2xl"
            style={{ background: "radial-gradient(circle, #fbf8f3 0%, #e8d6ae 60%, #d8b97a 100%)", color: "#4a331a" }}
          >
            {core.num}
          </span>
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-serif text-xl text-weave-800">{core.name}</h3>
              <span className="rounded-full px-2 py-0.5 text-[10px] uppercase tracking-widest text-treasure-700" style={{ background: "rgba(196,150,74,0.18)" }}>
                the treasure
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-sm text-weave-600 leading-relaxed">
              {core.blurb}
            </p>
          </div>
        </div>
      </div>

      <p className="mt-10 text-center text-sm text-weave-500 max-w-xl mx-auto">
        <span className="font-medium text-weave-700">Tax Optimizer</span> isn&apos;t a layer —
        it&apos;s a thread that runs through every ring, skimming the IRS
        setaside off every trade so wealth survives the year.
      </p>
    </section>
  );
}
