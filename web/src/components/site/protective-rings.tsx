/**
 * ProtectiveRings — concentric-ring SVG illustrating Trezo's Woven Basket.
 *
 * Layer 1 (Crypto Bot) is the outermost ring — takes the market's weather.
 * Layer 7 (KINDRIP) is the innermost — the children's portfolio, the actual
 * treasure being protected.
 *
 * Tax Optimizer is shown as a dashed outer band — a thread that wraps the
 * whole basket, taking a sliver from every layer for the IRS setaside.
 */

const LAYERS: { num: number; name: string; tag: string }[] = [
  { num: 1, name: "Crypto Bot",       tag: "24/7 volatility" },
  { num: 2, name: "Stock Bot (STMS)", tag: "morning momentum" },
  { num: 3, name: "Options Engine",   tag: "defined risk" },
  { num: 4, name: "Extended Strategy",tag: "swings + events" },
  { num: 5, name: "Dividend Wheel",   tag: "active income" },
  { num: 6, name: "Dividends",        tag: "passive income" },
  { num: 7, name: "KINDRIP",          tag: "the treasure" }
];

// Radii from outermost to innermost
const SIZE = 520;
const CX = SIZE / 2;
const CY = SIZE / 2;
const OUTER = 240;
const INNER = 26; // center disc radius
const STEP = (OUTER - INNER) / LAYERS.length;

// Color stops — outer = weave (calm green, the basket weave),
// inner = treasure (warm gold, the protected treasure).
function ringFill(i: number): string {
  // i: 0 = outermost, LAYERS.length-1 = innermost
  const palette = [
    "#28433b", // weave-700 outermost (toughest)
    "#36584d", // weave-600
    "#4a7062", // weave-500
    "#6c8e7f", // weave-400 transition
    "#c69a4f", // treasure-400
    "#b07d33", // treasure-500
    "#8e6228"  // treasure-600 innermost (next to gold core)
  ];
  return palette[Math.min(i, palette.length - 1)];
}

export function ProtectiveRings() {
  return (
    <figure className="mx-auto w-full max-w-[560px]">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label="Trezo Woven Basket — seven concentric protection rings"
        className="w-full h-auto"
      >
        <defs>
          <radialGradient id="treasure-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#fbf8f3" />
            <stop offset="60%" stopColor="#e8d6ae" />
            <stop offset="100%" stopColor="#d8b97a" />
          </radialGradient>
          <filter id="ring-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2" />
            <feOffset dx="0" dy="1" result="off" />
            <feComponentTransfer><feFuncA type="linear" slope="0.2" /></feComponentTransfer>
            <feMerge>
              <feMergeNode />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Tax Optimizer — dashed thread wrapping the whole basket */}
        <circle
          cx={CX}
          cy={CY}
          r={OUTER + 18}
          fill="none"
          stroke="#b07d33"
          strokeWidth={1.5}
          strokeDasharray="6 6"
          opacity={0.6}
        />
        <text
          x={CX}
          y={CY - OUTER - 30}
          textAnchor="middle"
          fontSize="11"
          fontFamily="ui-sans-serif, system-ui"
          letterSpacing="0.18em"
          fill="#8e6228"
          style={{ textTransform: "uppercase" }}
        >
          Tax Optimizer · wraps every layer
        </text>

        {/* Rings, outermost first so inner ones paint on top */}
        {LAYERS.map((layer, i) => {
          const ringInnerR = OUTER - (i + 1) * STEP;
          const ringOuterR = OUTER - i * STEP;
          const ringMidR = (ringInnerR + ringOuterR) / 2;

          // Donut via outer fill circle + inner cutout via mask
          const maskId = `mask-${i}`;
          return (
            <g key={layer.num} filter="url(#ring-shadow)">
              <mask id={maskId}>
                <rect x="0" y="0" width={SIZE} height={SIZE} fill="white" />
                <circle cx={CX} cy={CY} r={ringInnerR} fill="black" />
              </mask>
              <circle
                cx={CX}
                cy={CY}
                r={ringOuterR}
                fill={ringFill(i)}
                mask={`url(#${maskId})`}
                opacity={0.88}
              />
              {/* Layer label — centered along the top of each ring */}
              <text
                x={CX}
                y={CY - ringMidR + 4}
                textAnchor="middle"
                fontSize="11"
                fontWeight={500}
                fontFamily="ui-sans-serif, system-ui"
                fill="#fbf8f3"
                letterSpacing="0.04em"
              >
                {layer.num}. {layer.name}
              </text>
            </g>
          );
        })}

        {/* The treasure core — golden disc at center */}
        <circle cx={CX} cy={CY} r={INNER} fill="url(#treasure-core)" />
        <text
          x={CX}
          y={CY + 4}
          textAnchor="middle"
          fontSize="10"
          fontFamily="ui-serif, Georgia, serif"
          fontStyle="italic"
          fill="#4a331a"
        >
          treasure
        </text>
      </svg>

      <figcaption className="mt-4 text-center text-sm text-weave-600 max-w-md mx-auto leading-relaxed">
        Each ring protects the one beneath it. When one struggles, the others
        carry the weight — slowly, safely, ethically.
      </figcaption>
    </figure>
  );
}
