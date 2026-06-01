import { cn } from "@/lib/utils";

/**
 * EmptyCard - the dashed-border treasure-tinted "nothing here yet"
 * panel. Use whenever a list or table has zero rows so the absence
 * looks intentional rather than broken.
 */
export function EmptyCard({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-dashed border-weave-200 bg-treasure-100/40 p-6 text-sm text-weave-500 text-center leading-relaxed",
        className
      )}
    >
      {children}
    </div>
  );
}
