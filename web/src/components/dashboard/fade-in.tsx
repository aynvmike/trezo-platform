export function FadeIn({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ animation: "trezo-fade-in 0.32s cubic-bezier(0.22, 1, 0.36, 1) both" }}>
      {children}
    </div>
  );
}
