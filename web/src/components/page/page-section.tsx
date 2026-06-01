import { cn } from "@/lib/utils";

/**
 * PageSection - one logical block on a page. Treasure-color small-
 * caps header with a hairline gradient rule beneath, plus an
 * optional description sentence. Use these to group related
 * content visually so pages stop reading as one long scroll.
 */
export function PageSection({
  title,
  description,
  action,
  children,
  className,
}: {
  title?: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)}>
      {title ? (
        <div>
          <div className="flex items-baseline justify-between gap-3 flex-wrap">
            <h2 className="text-xs font-medium uppercase tracking-widest text-treasure-600">
              {title}
            </h2>
            {action ? <div className="shrink-0">{action}</div> : null}
          </div>
          <div
            aria-hidden="true"
            className="mt-1 h-px bg-gradient-to-r from-treasure-200/60 via-weave-100 to-transparent"
          />
          {description ? (
            <p className="mt-2 text-sm text-weave-600 leading-relaxed">
              {description}
            </p>
          ) : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
