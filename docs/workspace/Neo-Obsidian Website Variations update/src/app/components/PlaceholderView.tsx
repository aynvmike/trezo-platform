type Props = {
  title: string;
  description: string;
};

export function PlaceholderView({ title, description }: Props) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 py-12">
      <div
        className="w-12 h-12 rounded-xl flex items-center justify-center border border-border"
        style={{ background: "var(--card)" }}
      >
        <div className="w-3 h-3 rounded-full" style={{ background: "var(--treasure)", opacity: 0.6 }} />
      </div>
      <div className="text-center max-w-xs">
        <h2 className="text-[16px]" style={{ fontFamily: "var(--font-serif)", fontWeight: 500 }}>{title}</h2>
        <p className="text-[13px] mt-1.5" style={{ color: "var(--muted-foreground)" }}>{description}</p>
      </div>
      <div className="text-[11px] px-3 py-1.5 rounded-full border border-dashed border-border" style={{ color: "var(--muted-foreground)" }}>
        Coming soon
      </div>
    </div>
  );
}
