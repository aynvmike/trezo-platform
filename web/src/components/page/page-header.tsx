import { cn } from "@/lib/utils";

/**
 * PageHeader - Neo Obsidian page header. Every dashboard page uses
 * this so headers stay consistent and future page changes don't
 * have to relearn the pattern.
 *
 * Visual rhythm:
 *   - Treasure-color small-caps "tag" line (e.g. "Layer 5 — Wheel")
 *   - Serif h1 title (the page name)
 *   - Plain-language lede paragraph (one sentence, max two)
 *   - Optional beginner-only paragraph for first-time readers
 *   - Optional right-side action (button, link)
 */
export function PageHeader({
  tag,
  title,
  lede,
  beginnerCopy,
  action,
  className,
}: {
  tag?: string;
  title: string;
  lede?: string;
  beginnerCopy?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex items-start justify-between gap-4 flex-wrap",
        className
      )}
    >
      <div className="flex-1 min-w-0">
        {tag ? (
          <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
            {tag}
          </p>
        ) : null}
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          {title}
        </h1>
        {lede ? (
          <p className="mt-2 max-w-2xl text-sm text-weave-700 leading-relaxed">
            {lede}
          </p>
        ) : null}
        {beginnerCopy ? (
          <div className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
            {beginnerCopy}
          </div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
