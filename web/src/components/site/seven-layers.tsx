import { cn } from "@/lib/utils";

interface Layer {
  num: number;
  name: string;
  blurb: string;
  ring: "outer" | "mid" | "inner";
}

/**
 * Layer cards on the landing page. Order matches the protective-ring
 * metaphor: Layer 1 (outermost, most volatile) → Layer 7 (innermost,
 * most protected).
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

const RING_STYLE: Record<Layer["ring"], string> = {
  outer: "border-weave-200 bg-weave-50/40",
  mid:   "border-treasure-200 bg-treasure-50",
  inner: "border-treasure-300 bg-treasure-100"
};

export function SevenLayers() {
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
          From the outer ring (where the market hits hardest) to the inner
          vault (where your kids&apos; future lives), each layer protects the
          ones beneath it.
        </p>
      </div>

      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {LAYERS.map((layer) => (
          <li
            key={layer.num}
            className={cn(
              "relative rounded-xl border p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md",
              RING_STYLE[layer.ring]
            )}
          >
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-white font-serif text-treasure-700 ring-1 ring-treasure-200">
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
        ))}
      </ol>

      <p className="mt-10 text-center text-sm text-weave-500 max-w-xl mx-auto">
        <span className="font-medium text-weave-700">Tax Optimizer</span> isn&apos;t a layer —
        it&apos;s a thread that runs through every ring, skimming the IRS
        setaside off every trade so wealth survives the year.
      </p>
    </section>
  );
}
