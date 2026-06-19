export function AmbientBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" style={{ zIndex: 0 }}>
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: "radial-gradient(circle, rgb(var(--border)) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
          opacity: 0.4,
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
        }}
      />
      <div className="absolute rounded-full" style={{ width: 520, height: 520, left: "-15%", top: "-10%", background: "radial-gradient(circle, rgb(var(--primary)) 0%, transparent 65%)", opacity: 0.1, filter: "blur(60px)" }} />
      <div className="absolute rounded-full" style={{ width: 460, height: 460, right: "-12%", bottom: "-10%", background: "radial-gradient(circle, rgb(56 189 248) 0%, transparent 65%)", opacity: 0.08, filter: "blur(70px)" }} />
      <div className="absolute rounded-full" style={{ width: 320, height: 320, right: "20%", top: "30%", background: "radial-gradient(circle, rgb(var(--emerald-500)) 0%, transparent 65%)", opacity: 0.06, filter: "blur(60px)" }} />
    </div>
  );
}
