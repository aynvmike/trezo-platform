/**
 * ProtectiveRings — the Woven Basket as a 3D atom (CSS 3D, no JS).
 * Ported to the Neo-Obsidian "update 2" AtomHero design: seven tilted gold
 * shells (Layer 1 outermost → 7 innermost) each carrying TWO counter-orbiting
 * electrons colored by that layer's risk accent, around a pulsing treasure
 * nucleus; the whole atom tumbles on multiple axes.
 */

const SHELLS = [
  { d: 410, rx: 70, ry: 0,   c: "244 63 94",  dur: 13 }, // 1 Crypto — rose
  { d: 360, rx: 60, ry: 30,  c: "245 158 11", dur: 12 }, // 2 Stock — amber
  { d: 310, rx: 50, ry: 60,  c: "56 189 248", dur: 11 }, // 3 Options — sky
  { d: 262, rx: 75, ry: 90,  c: "196 150 74", dur: 10 }, // 4 Extended — gold
  { d: 214, rx: 65, ry: 120, c: "16 185 129", dur: 9 },  // 5 Wheel — emerald
  { d: 168, rx: 55, ry: 150, c: "56 189 248", dur: 8 },  // 6 Dividends — sky
  { d: 122, rx: 45, ry: 180, c: "196 150 74", dur: 7 },  // 7 KINDRIP — gold
];

export function ProtectiveRings() {
  return (
    <figure className="mx-auto w-full max-w-[560px]">
      <div className="trezo-atom-scene" role="img" aria-label="Trezo Woven Basket — a 3D atom of seven orbital shells circling a treasure nucleus">
        <div className="trezo-atom">
          <div className="trezo-atom-glow" />
          {SHELLS.map((s, i) => {
            const r = s.d / 2;
            const e1 = Math.max(5, 10 - i * 0.6);
            return (
              <div
                key={i}
                className="trezo-orbit"
                style={{ width: s.d, height: s.d, transform: `translate(-50%, -50%) rotateX(${s.rx}deg) rotateY(${s.ry}deg)` }}
              >
                <div
                  className="trezo-orbit-ring"
                  style={{ borderColor: "rgba(196, 150, 74, 0.32)", boxShadow: `inset 0 0 ${Math.round(s.d / 6)}px rgba(196, 150, 74, 0.08)` }}
                />
                {/* electron 1 — clockwise */}
                <div className="trezo-orbit-spinner" style={{ animationDuration: `${s.dur}s`, animationDirection: "normal" }}>
                  <div
                    className="trezo-electron"
                    style={{
                      width: e1, height: e1,
                      transform: `translate(-50%, -50%) translateX(${r}px)`,
                      background: `radial-gradient(circle at 30% 30%, #ffffff 0%, rgb(${s.c}) 42%, transparent 100%)`,
                      boxShadow: `0 0 12px rgb(${s.c})`,
                    }}
                  />
                </div>
                {/* electron 2 — counter-clockwise, opposite side */}
                <div className="trezo-orbit-spinner" style={{ animationDuration: `${s.dur + 2}s`, animationDirection: "reverse" }}>
                  <div
                    className="trezo-electron"
                    style={{
                      width: 6, height: 6, opacity: 0.7,
                      transform: `translate(-50%, -50%) translateX(-${r}px)`,
                      background: `radial-gradient(circle at 30% 30%, #ffffff 0%, rgb(${s.c}) 50%, transparent 100%)`,
                      boxShadow: `0 0 8px rgb(${s.c})`,
                    }}
                  />
                </div>
              </div>
            );
          })}
          <div className="trezo-nucleus" />
        </div>
      </div>

      <figcaption className="mt-6 text-center text-sm text-[rgb(var(--muted-foreground))] max-w-md mx-auto leading-relaxed">
        Seven shells in constant motion around one core — each layer protects the
        one beneath it. When one struggles, the others carry the weight.
      </figcaption>
    </figure>
  );
}
