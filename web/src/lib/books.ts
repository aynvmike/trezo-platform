/**
 * Which BOOKS does this person own? (rv:web-pages MAJOR, overview-data :122)
 *
 * Since migration 0047, `user_id` on every book table (paper_accounts,
 * paper_positions, options_positions, trade_outcomes, exit_advisor_alerts,
 * ...) is the BOOK key -- trading_accounts.account_key -- not the person's
 * auth uid. A person owns several books (Mike: primary, 25k, 75k), and the
 * dashboard pages were still scoping every read `.eq("user_id", auth uid)`,
 * so the owner saw one book (or none, when the auth uid is not itself a
 * book key) presented as the whole picture: "0 of 8 active" while the
 * brokers held positions.
 *
 * Resolve the books the way settings/bot/page.tsx does -- trading_accounts
 * where owner_id = user.id and is_active -- and query `.in("user_id", keys)`.
 * RLS (0047 `my_account_keys()`) already limits book rows to the caller's
 * own books, so this cannot surface someone else's positions; it only stops
 * hiding the caller's.
 *
 * House rules honoured here:
 *   - a failed trading_accounts read is a FAILURE (LoadResult), never an
 *     empty book list -- use `withBooks()` so dependent reads inherit it;
 *   - an unresolvable book is skipped, never GUESSED (`resolveBookKey`
 *     returns null rather than picking one of several books). Note the
 *     owner's own uid IS a book key for Mike (0045 registers the primary
 *     with account_key = owner_id), so it resolves by rule, not by guess.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import type { LoadResult } from "@/components/dashboard/load-error";

export type BookKeysLoad = LoadResult<string[]>;

/** A uuid no book can have; keeps `.in("user_id", ...)` well-formed when
 *  a person owns no active book (the same trick kindrip/page.tsx uses). */
export const NO_BOOK_SENTINEL = "00000000-0000-0000-0000-000000000000";

/** Active book keys owned by `userId`. `data: null` + failure when the
 *  read itself failed (logged, message only). An owner with no active
 *  book gets `data: []`, which is a real answer. */
export async function getOwnerBookKeys(
  supabase: SupabaseClient,
  userId: string
): Promise<BookKeysLoad> {
  const { data, error } = await supabase
    .from("trading_accounts")
    .select("account_key")
    .eq("owner_id", userId)
    .eq("is_active", true);
  if (error) {
    console.error(`[load] trading_accounts: ${error.message}`);
    return { data: null, failure: { table: "trading_accounts", message: error.message } };
  }
  const keys = ((data ?? []) as { account_key: unknown }[])
    .map((r) => String(r.account_key ?? ""))
    .filter(Boolean);
  return { data: keys, failure: null };
}

/** Keys for `.in("user_id", ...)`: never an empty list. */
export function bookQueryKeys(keys: string[] | null): string[] {
  return keys && keys.length > 0 ? keys : [NO_BOOK_SENTINEL];
}

/** A read scoped by book keys inherits the key-resolution failure: when
 *  the books could not be resolved, the rows must not read as "empty". */
export function withBooks<T>(books: BookKeysLoad, res: LoadResult<T>): LoadResult<T> {
  return books.failure ? { data: null, failure: books.failure } : res;
}

/**
 * Which ONE book an action targets. `requested` (e.g. a body `account_key`)
 * must be one of the caller's books; without it, the caller's own uid when
 * it is a book, else the only book they own. Anything else is null -- the
 * caller must say which book; we never GUESS among several.
 *
 * vf:config-web :77 -- be precise about what that means for the one real
 * owner: migration 0045 registers the PRIMARY book with
 * account_key = owner_id, so Mike's auth uid IS the primary's key and
 * `keys.includes(userId)` legitimately selects the primary whenever
 * `requested` is omitted (same target the routes had before books existed).
 * Callers that must never land on the primary by omission have to pass
 * `requested` explicitly; this function does not refuse the uid rule.
 */
export function resolveBookKey(
  keys: string[],
  userId: string,
  requested?: string | null
): string | null {
  const want = (requested ?? "").trim();
  if (want) return keys.includes(want) ? want : null;
  if (keys.includes(userId)) return userId;
  return keys.length === 1 ? keys[0] : null;
}
