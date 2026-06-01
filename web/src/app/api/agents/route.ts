import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/agents → list of agent state objects, always an array.
 * If the upstream is unreachable or returns a non-array body (404, error
 * payload, etc.), returns `{ agents: [], error: "..." }` so the UI can show
 * a friendly empty state instead of throwing on `.map()`.
 */
export async function GET() {
  try {
    const r = await fetch(`${AGENTS_BASE}/agents`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    const body = await r.json().catch(() => null);
    if (!r.ok) {
      return NextResponse.json(
        {
          agents: [],
          error: `Agents service returned ${r.status}. Restart it via start-agents.bat after applying migration 0007.`
        },
        { status: 200 }
      );
    }
    if (!Array.isArray(body)) {
      return NextResponse.json(
        {
          agents: [],
          error:
            "Agents service responded but with unexpected shape. The endpoint /agents may be from an older build — restart start-agents.bat."
        },
        { status: 200 }
      );
    }
    return NextResponse.json({ agents: body });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Agents service unreachable";
    return NextResponse.json(
      {
        agents: [],
        error: `${msg}. Make sure start-agents.bat is running on port 8001.`
      },
      { status: 200 }
    );
  }
}
