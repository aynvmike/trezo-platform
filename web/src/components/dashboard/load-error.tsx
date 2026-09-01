/**
 * PAGES-03: a failed Supabase read must never render as a plausible
 * empty state. Every dashboard data page used to do `res.data ?? []`,
 * which makes "the query errored" indistinguishable from "nothing there"
 * (and /tax showed "$0 owed" on a failed query). Same lesson as the
 * broker rule in CLAUDE.md: a read that fails must never read as empty.
 *
 * Usage (server components):
 *
 *   const open = loadResult("paper_positions", openRes);
 *   ...
 *   {open.failure ? <LoadError {...open.failure} /> : open.data.length === 0 ? <Empty/> : <Table/>}
 *
 * `loadResult` logs the error server-side (message only — never a
 * secret) and returns a discriminated union so the page has to decide
 * what to show; it cannot accidentally fall through to the empty copy.
 */

export type LoadFailure = { table: string; message: string };

export type LoadResult<T> =
  | { data: T; failure: null }
  | { data: null; failure: LoadFailure };

type SupabaseLike<T> = {
  data: T | null;
  error: { message: string } | null;
};

/**
 * Wrap a Supabase response. On error: log + return `{ data: null, failure }`.
 * On success: return `res.data`, or `fallback` when the row set is null
 * (a `maybeSingle()` with no row is a legitimate null — pass no fallback
 * and the caller keeps `T | null` semantics by typing T as nullable).
 */
export function loadResult<T>(
  table: string,
  res: SupabaseLike<T>,
  fallback?: T
): LoadResult<T> {
  if (res.error) {
    console.error(`[load] ${table}: ${res.error.message}`);
    return { data: null, failure: { table, message: res.error.message } };
  }
  const data = (res.data ?? fallback) as T;
  return { data, failure: null };
}

/** The non-null failures from a set of results, for a page-level banner. */
export function failuresOf(...results: LoadResult<unknown>[]): LoadFailure[] {
  return results.flatMap((r) => (r.failure ? [r.failure] : []));
}

export function LoadError({ table, message }: LoadFailure) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-relaxed text-amber-900"
    >
      <span className="font-medium">Could not load — {table}.</span>{" "}
      Anything on this page that depends on it is missing, not zero. Reload;
      if it keeps failing, the table or its policy may need attention in
      Supabase.
      {message ? (
        <span className="mt-1 block font-mono text-[11px] text-amber-800/80">
          {message}
        </span>
      ) : null}
    </div>
  );
}

/** One card per failed table, or nothing when every read succeeded. */
export function LoadErrors({ failures }: { failures: LoadFailure[] }) {
  if (failures.length === 0) return null;
  return (
    <div className="space-y-3">
      {failures.map((f) => (
        <LoadError key={f.table} {...f} />
      ))}
    </div>
  );
}
