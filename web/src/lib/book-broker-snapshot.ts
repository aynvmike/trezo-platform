/** An explicit book is required; never borrow another account's balance. */
export async function fetchBookBrokerSnapshot(accountKey: string): Promise<{
  equity: number;
  options_approved_level: number;
  trading_blocked: boolean;
} | null> {
  if (!accountKey) return null;
  const base = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";
  try {
    const response = await fetch(`${base}/broker/snapshot?user_id=${encodeURIComponent(accountKey)}`, {
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) return null;
    const result = await response.json();
    if (!result?.snapshot) return null;
    return result.snapshot;
  } catch { return null; }
}
