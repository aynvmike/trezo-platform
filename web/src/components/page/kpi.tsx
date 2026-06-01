import { cn } from "@/lib/utils";

/**
 * KpiGrid + KpiTile - the standard headline-tile pattern.
 * Treasure-color uppercase label, mono-font value, optional tone +
 * "Live" badge for broker-truth data.
 */
export function KpiGrid({
  cols = 4,
  children,
  className,
}: {
  cols?: 2 | 3 | 4 | 5;
  children: React.ReactNode;
  className?: string;
}) {
  const colMap: Record<number, string> = {
    2: "grid-cols-2",
    3: "grid-cols-2 sm:grid-cols-3",
    4: "grid-cols-2 sm:grid-cols-4",
    5: "grid-cols-2 sm:grid-cols-5",
  };
  return (
    <section className={cn("grid gap-3", colMap[cols], className)}>
      {children}
    </section>
  );
}

export function KpiTile({
  label,
  value,
  tone,
  live,
  hint,
}: {
  label: string;
  value: string | number;
  tone?: "good" | "bad" | "treasure" | "neutral";
  live?: boolean;
  hint?: string;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-700"
      : tone === "bad"
      ? "text-red-600"
      : tone === "treasure"
      ? "text-treasure-700"
      : "text-weave-800";

  return (
    <div
      className="rounded-xl border border-weave-100 bg-white p-4"
      title={hint}
    >
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[11px] uppercase tracking-widest text-weave-500">
          {label}
        </p>
        {live ? (
          <span
            className="text-[9px] uppercase tracking-widest rounded-full bg-emerald-100 text-emerald-800 px-1.5 py-0.5"
            title="Sourced from the live broker, not modeled data."
          >
            Live
          </span>
        ) : null}
      </div>
      <p className={cn("mt-1 font-mono text-lg font-medium", toneClass)}>
        {value}
      </p>
    </div>
  );
}
