import type { ReactNode } from "react";

/**
 * A collapsible section built on native <details> — no client JS.
 * Used to keep dense pages compact: secondary content (guides, "how it
 * works", deferred notes) collapses by default so there is less to
 * scroll. The chevron rotates via the `group-open` Tailwind variant.
 */
export function Disclosure({
  title,
  hint,
  children,
  defaultOpen = false
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details
      className="group rounded-xl border border-weave-100 bg-white"
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 select-none">
        <span className="font-medium text-weave-800">
          {title}
          {hint && (
            <span className="ml-2 text-sm font-normal text-weave-500">{hint}</span>
          )}
        </span>
        <svg
          className="h-4 w-4 shrink-0 text-weave-400 transition-transform group-open:rotate-180"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </summary>
      <div className="border-t border-weave-50 px-5 py-4 text-sm text-weave-600 leading-relaxed">
        {children}
      </div>
    </details>
  );
}
