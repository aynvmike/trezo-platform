import { MarketSidePanel } from "./market-side-panel";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

type Snapshot = {
  assets?: Record<string, unknown>;
  correlations?: unknown[];
  summary?: string;
};

type MacroSnap = {
  configured: boolean;
};

async function loadSnapshot(): Promise<Snapshot | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/markets/pulse`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    if (!r.ok) return null;
    return (await r.json()) as Snapshot;
  } catch {
    return null;
  }
}

async function loadMacro(): Promise<MacroSnap | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/macro/snapshot`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    if (!r.ok) return null;
    return (await r.json()) as MacroSnap;
  } catch {
    return null;
  }
}

/**
 * Server-side wrapper that fetches both feeds in parallel, then hands
 * them to the client-side MarketSidePanel. Keeps the data fetch on
 * the server (no client API key, no waterfall) while the tabbed UI
 * stays interactive.
 */
export async function MarketSidePanelServer() {
  const [snapshot, macro] = await Promise.all([loadSnapshot(), loadMacro()]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return <MarketSidePanel snapshot={snapshot as any} macro={macro as any} />;
}
