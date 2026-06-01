/**
 * MiniChart — a compact SVG candlestick snapshot of recent price action.
 * Used on the Pattern Engine cards so the user can see what the detector
 * looked at. No charting library — a hand-drawn SVG keeps it light and
 * sleek. Up candles green, down candles red; reads on light and dark.
 *
 * `highlightLast` tints the last N candles — used to mark roughly where
 * the detected candlestick pattern formed.
 */
type Bar = { o: number; h: number; l: number; c: number };

export function MiniChart({
  candles,
  height = 76,
  highlightLast = 0
}: {
  candles: Bar[];
  height?: number;
  highlightLast?: number;
}) {
  const W = 320;
  const H = height;
  const pad = 6;

  if (!candles || candles.length < 2) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-weave-100 bg-weave-50/40 text-[11px] text-weave-400"
        style={{ height: H }}
      >
        No chart data
      </div>
    );
  }

  const hi = Math.max(...candles.map((c) => c.h));
  const lo = Math.min(...candles.map((c) => c.l));
  const span = hi - lo || 1;
  const n = candles.length;
  const slot = W / n;
  const bodyW = Math.max(1.5, slot * 0.62);
  const y = (price: number) => pad + ((hi - price) / span) * (H - 2 * pad);

  const markN = Math.max(0, Math.min(highlightLast, n));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full rounded-lg border border-weave-100 bg-weave-50/40"
      style={{ height: H }}
      role="img"
      aria-label="Recent price snapshot"
    >
      {markN > 0 && (
        <rect
          x={slot * (n - markN)}
          y={0}
          width={slot * markN}
          height={H}
          fill="#c9a86e"
          fillOpacity={0.16}
        />
      )}
      {candles.map((c, i) => {
        const xc = slot * i + slot / 2;
        const up = c.c >= c.o;
        const color = up ? "#10b981" : "#f87171";
        const bodyTop = Math.min(y(c.o), y(c.c));
        const bodyH = Math.max(1, Math.abs(y(c.o) - y(c.c)));
        return (
          <g key={i}>
            <line
              x1={xc}
              x2={xc}
              y1={y(c.h)}
              y2={y(c.l)}
              stroke={color}
              strokeWidth={1}
              opacity={0.65}
            />
            <rect
              x={xc - bodyW / 2}
              y={bodyTop}
              width={bodyW}
              height={bodyH}
              fill={color}
            />
          </g>
        );
      })}
    </svg>
  );
}
