/**
 * Unified cache layer.
 *
 * Uses Upstash Redis (via REST API) if UPSTASH_REDIS_REST_URL and
 * UPSTASH_REDIS_REST_TOKEN are set; otherwise falls back to an in-process
 * Map (per-server-instance, lost on restart). The fallback is fine for
 * local dev — production should plug Upstash in.
 */

type Entry<T> = { value: T; expiresAt: number };
const memory = new Map<string, Entry<unknown>>();

function hasUpstash(): boolean {
  return Boolean(
    process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN
  );
}

async function redisGet<T>(key: string): Promise<T | null> {
  try {
    const r = await fetch(
      `${process.env.UPSTASH_REDIS_REST_URL}/get/${encodeURIComponent(key)}`,
      {
        headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
        cache: "no-store"
      }
    );
    if (!r.ok) return null;
    const j = (await r.json()) as { result: string | null };
    return j.result ? (JSON.parse(j.result) as T) : null;
  } catch {
    return null;
  }
}

async function redisSet<T>(key: string, value: T, ttlSec: number): Promise<void> {
  try {
    const encVal = encodeURIComponent(JSON.stringify(value));
    await fetch(
      `${process.env.UPSTASH_REDIS_REST_URL}/set/${encodeURIComponent(key)}/${encVal}?EX=${ttlSec}`,
      {
        headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
        cache: "no-store"
      }
    );
  } catch {
    // best-effort: ignore cache write errors
  }
}

export async function cacheGet<T>(key: string): Promise<T | null> {
  if (hasUpstash()) return redisGet<T>(key);
  const e = memory.get(key) as Entry<T> | undefined;
  if (!e) return null;
  if (e.expiresAt < Date.now()) {
    memory.delete(key);
    return null;
  }
  return e.value;
}

export async function cacheSet<T>(
  key: string,
  value: T,
  ttlSec: number
): Promise<void> {
  if (hasUpstash()) return redisSet<T>(key, value, ttlSec);
  memory.set(key, { value, expiresAt: Date.now() + ttlSec * 1000 });
}

/**
 * Returns cached value if present, else calls `fetcher`, caches the result,
 * and returns it. Use this for all upstream API calls.
 */
export async function cacheGetOrSet<T>(
  key: string,
  ttlSec: number,
  fetcher: () => Promise<T>
): Promise<T> {
  const cached = await cacheGet<T>(key);
  if (cached !== null) return cached;
  const fresh = await fetcher();
  await cacheSet(key, fresh, ttlSec);
  return fresh;
}
