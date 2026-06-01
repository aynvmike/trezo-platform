import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export async function POST(
  request: Request,
  { params }: { params: { name: string } }
) {
  // Auth guard — toggling an agent on/off is a state change, so a valid
  // signed-in session is required before the request is proxied.
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  try {
    const body = await request.json();
    const r = await fetch(`${AGENTS_BASE}/agents/${encodeURIComponent(params.name)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    const j = await r.json();
    return NextResponse.json(j, { status: r.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Toggle failed" },
      { status: 502 }
    );
  }
}
