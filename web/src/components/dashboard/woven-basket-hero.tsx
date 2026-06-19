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

export function WovenBasketHero({ layers }: { layers?: HeroLayer[] }) {
  const L = layers && layers.length ? layers : SAMPLE;
  const total = L.reduce((s, l) => s + l.pnl, 0);
  const active = L.filter((l) => l.status === "active").length;
  const totalStr = (total >= 0 ? "+" : "-") + "$" + Math.abs(total).toFixed(0);
  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] depth-raised"
      style={{ minHeight: 220, animation: "trezo-fade-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) both" }}
    >
      <div className="pointer-events-none absolute inset-0" style={{ background: "linear-gradient(135deg, rgba(196,150,74,0.06) 0%, transparent 35%, transparent 65%, rgba(196,150,74,0.03) 100%)" }} />
      <div className="relative grid grid-cols-1 md:grid-cols-2">
        <div className="relative flex h-[220px] items-center justify-center overflow-hidden">
          {L.map((layer, i) => {
            const size = 200 - i * 22;
            const isOn = layer.status === "active";
            return (
              <div
                key={layer.id}
                className="absolute rounded-full"
                style={{ width: size, height: size, border: "1px solid " + (isOn ? "rgb(var(--primary))" : "rgb(var(--border))"), opacity: isOn ? 0.85 - i * 0.06 : 0.2 }}
              />
            );
          })}
          <div className="absolute rounded-full animate-pulse" style={{ width: 28, height: 28, background: "radial-gradient(circle, rgb(var(--primary)) 0%, transparent 70%)" }} />
          {[1, 2, 3, 5, 7].map((n) => {
            const radius = 100 - (n - 1) * 11;
            return (
              <div key={"orbit-" + n} className="absolute animate-spin" style={{ width: radius * 2, height: radius * 2, animationDuration: 20 + n * 4 + "s" }}>
                <div className="absolute left-1/2 top-0 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ background: "rgb(var(--primary))", boxShadow: "0 0 8px rgb(var(--primary))" }} />
              </div>
            );
          })}
        </div>
        <div className="flex flex-col justify-center gap-4 px-6 py-6">
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-treasure-400">Woven Basket</div>
            <h2 className="font-serif text-[26px] font-medium leading-[1.15] text-[rgb(var(--foreground))]">
              Seven layers,
              <br />
              one strategy
            </h2>
            <p className="mt-2 text-[12px] text-[rgb(var(--muted-foreground))]">Outer rings carry volatility, inner rings carry protection. Every ring earns its keep.</p>
          </div>
          <div className="flex items-center gap-5 border-t border-[rgb(var(--border))] pt-2">
            <div>
              <div className={"font-mono text-[18px] font-medium " + (total >= 0 ? "text-emerald-500" : "text-red-500")}>{totalStr}</div>
              <div className="text-[10px] tracking-wide text-[rgb(var(--muted-foreground))]">{"TODAY'S P&L"}</div>
            </div>
            <div>
              <div className="font-mono text-[18px] font-medium text-[rgb(var(--foreground))]">{active}/7</div>
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
