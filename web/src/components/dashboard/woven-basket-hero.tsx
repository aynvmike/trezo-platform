/**
 * WovenBasketHero — the Overview hero, now the SAME CSS-3D atom as the
 * landing page (Mike 2026-07-13: the flat rings did not show which
 * layers are actually working; the landing atom feels interactive).
 * Every shell = one wealth layer, outermost (Layer 1) to innermost.
 * A shell whose layer holds a position right now burns bright with two
 * counter-orbiting electrons; an idle shell dims to a faint ring with a
 * single slow ember. Live data in, honest picture out.
 *
 * FUTURE (Mike 2026-07-13): make the orbs the navigation — click a
 * shell to open that layer's page and retire the side column. Needs
 * hit-testing on the 3D transforms; parked for the next design pass.
 */

export type HeroLayer = { id: number; name: string; status: string; pnl: number };

const SAMPLE: HeroLayer[] = [
  { id: 1, name: "Crypto", status: "active", pnl: 417.5 },
  { id: 2, name: "Stock", status: "active", pnl: 221.25 },
  { id: 3, name: "Options", status: "active", pnl: 545.0 },
  { id: 4, name: "Stock Weekly", status: "idle", pnl: 0 },
  { id: 5, name: "Wheel", status: "active", pnl: 180.0 },
  { id: 6, name: "Dividends", status: "paused", pnl: 0 },
  { id: 7, name: "KINDRIP", status: "active", pnl: 92.0 },
];

// Accent + tilt per shell position (outermost first), echoing the landing atom.
const SHELL_ACCENTS = [
  { c: "244 63 94", rx: 70, ry: 0, dur: 13 },   // rose
  { c: "245 158 11", rx: 60, ry: 30, dur: 12 }, // amber
  { c: "56 189 248", rx: 50, ry: 60, dur: 11 }, // sky
  { c: "196 150 74", rx: 75, ry: 90, dur: 10 }, // gold
  { c: "16 185 129", rx: 65, ry: 120, dur: 9 }, // emerald
  { c: "56 189 248", rx: 55, ry: 150, dur: 8 }, // sky
  { c: "196 150 74", rx: 45, ry: 180, dur: 7 }, // gold
  { c: "168 85 247", rx: 62, ry: 210, dur: 14 }, // violet (Layer 8 — Forex)
];

export function WovenBasketHero({ layers }: { layers?: HeroLayer[] }) {
  const L = layers && layers.length ? layers : SAMPLE;
  const total = L.reduce((s, l) => s + l.pnl, 0);
  const active = L.filter((l) => l.status === "active").length;
  const totalStr = (total >= 0 ? "+" : "-") + "$" + Math.abs(total).toFixed(0);
  const outer = 238; // outermost shell diameter (px) inside the 250px scene
  const step = L.length > 1 ? (outer - 66) / (L.length - 1) : 0;
  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] depth-raised"
      style={{ minHeight: 264, animation: "trezo-fade-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) both" }}
    >
      <div className="pointer-events-none absolute inset-0" style={{ background: "linear-gradient(135deg, rgba(196,150,74,0.06) 0%, transparent 35%, transparent 65%, rgba(196,150,74,0.03) 100%)" }} />
      <div className="relative grid grid-cols-1 md:grid-cols-2">
        <div className="relative flex h-[264px] items-center justify-center overflow-hidden">
          <div className="trezo-atom-scene" style={{ width: 252, maxWidth: 252 }}>
            <div className="trezo-atom">
              <div className="trezo-atom-glow" />
              {L.map((layer, i) => {
                const a = SHELL_ACCENTS[i % SHELL_ACCENTS.length];
                const d = Math.round(outer - i * step);
                const r = d / 2;
                const on = layer.status === "active";
                const rgb = a.c.split(" ").join(",");
                return (
                  <div
                    key={layer.id}
                    className="trezo-orbit"
                    title={layer.name + " — " + layer.status}
                    style={{ width: d, height: d, transform: `translate(-50%, -50%) rotateX(${a.rx}deg) rotateY(${a.ry}deg)` }}
                  >
                    <div
                      className="trezo-orbit-ring"
                      style={{
                        borderColor: on ? "rgba(196, 150, 74, 0.55)" : "rgba(196, 150, 74, 0.13)",
                        boxShadow: on
                          ? `inset 0 0 ${Math.round(d / 6)}px rgba(196,150,74,0.12), 0 0 10px rgba(${rgb}, 0.18)`
                          : "none",
                      }}
                    />
                    {/* electron 1 — every layer keeps one ember so the basket never looks dead */}
                    <div className="trezo-orbit-spinner" style={{ animationDuration: `${on ? a.dur : a.dur * 2.2}s`, animationDirection: "normal" }}>
                      <div
                        className="trezo-electron"
                        style={{
                          width: on ? 8 : 4, height: on ? 8 : 4, opacity: on ? 1 : 0.35,
                          transform: `translate(-50%, -50%) translateX(${r}px)`,
                          background: `radial-gradient(circle at 30% 30%, #ffffff 0%, rgb(${a.c}) 45%, transparent 100%)`,
                          boxShadow: on ? `0 0 12px rgb(${a.c})` : "none",
                        }}
                      />
                    </div>
                    {/* electron 2 — only layers holding a position earn the counter-orbit */}
                    {on ? (
                      <div className="trezo-orbit-spinner" style={{ animationDuration: `${a.dur + 2}s`, animationDirection: "reverse" }}>
                        <div
                          className="trezo-electron"
                          style={{
                            width: 5, height: 5, opacity: 0.75,
                            transform: `translate(-50%, -50%) translateX(-${r}px)`,
                            background: `radial-gradient(circle at 30% 30%, #ffffff 0%, rgb(${a.c}) 50%, transparent 100%)`,
                            boxShadow: `0 0 8px rgb(${a.c})`,
                          }}
                        />
                      </div>
                    ) : null}
                  </div>
                );
              })}
              <div className="trezo-nucleus" />
            </div>
          </div>
        </div>
        <div className="flex flex-col justify-center gap-4 px-6 py-6">
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-treasure-400">Woven Basket</div>
            <h2 className="font-serif text-[26px] font-medium leading-[1.15] text-[rgb(var(--foreground))]">
              Seven layers,
              <br />
              one strategy
            </h2>
            <p className="mt-2 text-[12px] text-[rgb(var(--muted-foreground))]">Every shell is a live agent lane — a lit orbit holds a position right now. Two electrons means the lane is working.</p>
          </div>
          <div className="flex items-center gap-5 border-t border-[rgb(var(--border))] pt-2">
            <div>
              <div className={"font-mono text-[18px] font-medium " + (total >= 0 ? "text-emerald-500" : "text-red-500")}>{totalStr}</div>
              <div className="text-[10px] tracking-wide text-[rgb(var(--muted-foreground))]">{"TODAY'S P&L"}</div>
            </div>
            <div>
              <div className="font-mono text-[18px] font-medium text-[rgb(var(--foreground))]">{active}/{L.length}</div>
              <div className="text-[10px] tracking-wide text-[rgb(var(--muted-foreground))]">ACTIVE</div>
            </div>
            <div className="ml-auto flex gap-1.5">
              {L.map((l) => (
                <div
                  key={l.id}
                  title={l.name + " - " + l.status}
                  className={"flex h-5 w-5 items-center justify-center rounded font-mono text-[9px] font-medium " + (l.status === "active" ? "bg-[rgb(var(--primary))] text-[rgb(var(--background))]" : "bg-[rgb(var(--muted))] text-[rgb(var(--muted-foreground))] opacity-50")}
                >
                  {l.id}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
