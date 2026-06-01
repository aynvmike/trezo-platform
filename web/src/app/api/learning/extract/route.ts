import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/learning/extract
 *
 * Accepts a multipart upload (field name "file") of a PDF, image,
 * Excel sheet, Word doc, or plain text and forwards to the agents
 * service. The agents service runs the document through Claude with
 * a structured-extraction prompt and returns parsed trade rows.
 *
 * The web layer doesn't import the file's contents into trade_outcomes
 * yet — the user reviews the extracted rows first and confirms with a
 * separate POST to /api/learning/import. That two-step (extract,
 * preview, import) is intentional so the user can catch hallucinations
 * before they hit the learning ledger.
 */
export async function POST(req: Request) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json(
      { ok: false, error: "Not signed in." },
      { status: 401 }
    );
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json(
      { ok: false, error: "Body must be multipart/form-data." },
      { status: 400 }
    );
  }

  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json(
      { ok: false, error: "Attach a file as 'file'." },
      { status: 400 }
    );
  }
  if (file.size > 10 * 1024 * 1024) {
    return NextResponse.json(
      { ok: false, error: "Files larger than 10MB aren't supported." },
      { status: 400 }
    );
  }

  const fwd = new FormData();
  fwd.set("file", file, file.name);

  try {
    const r = await fetch(`${AGENTS_BASE}/learning/extract`, {
      method: "POST",
      body: fwd,
      signal: AbortSignal.timeout(120_000),
    });
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      return NextResponse.json(
        { ok: false, error: `Agents returned ${r.status}: ${text.slice(0, 200)}` },
        { status: 502 }
      );
    }
    const data = await r.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: e instanceof Error ? e.message : "Network error" },
      { status: 502 }
    );
  }
}
