import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * Which BOOK these settings apply to.
 *
 * Until 2026-08-09 this page edited one row keyed by the signed-in user,
 * because a person had exactly one book. A person can hold several --
 * individual, IRA, joint, or several paper books under one broker login --
 * and posture, risk, max-open and the lane toggles are properties of a
 * BOOK, not of a person. A $75k book should not inherit a $4.9k book's
 * dials just because the same human owns both.
 *
 * Reads `trading_accounts`, whose RLS restricts rows to `owner_id =
 * auth.uid()`, so a person only ever sees their own books.
 */

export type BookOption = {
  account_key: string;
  label: string | null;
  is_paper: boolean;
  starting_capital_usd: number | null;
};

function money(n: number | null): string {
  if (n === null || !Number.isFinite(n)) return "—";
  return n >= 1000
    ? `$${Math.round(n / 1000)}k`
    : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function AccountSwitcher({
  books,
  activeKey
}: {
  books: BookOption[];
  activeKey: string;
}) {
  // One book: the concept adds nothing, so don't put a chooser on screen.
  if (books.length <= 1) return null;

  return (
    <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      <div className="space-y-1">
        <p className="text-sm font-medium">Which account are you tuning?</p>
        <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
          Every dial below belongs to the selected account. Changing risk here
          does not touch your other books.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {books.map((b) => {
          const active = b.account_key === activeKey;
          return (
            <Link
              key={b.account_key}
              href={`/dashboard/settings/bot?account=${b.account_key}`}
              aria-current={active ? "page" : undefined}
              className={cn(
                "rounded-lg border px-3 py-2 text-sm transition-colors",
                active
                  ? "border-emerald-400/60 bg-emerald-500/10 text-emerald-200"
                  : "border-[var(--border)] hover:bg-[var(--surface)]"
              )}
            >
              <span className="font-medium">{b.label ?? "Account"}</span>
              <span className="ml-2 text-xs opacity-70">
                {money(b.starting_capital_usd)}
                {b.is_paper ? " · paper" : " · live"}
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
