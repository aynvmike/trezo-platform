import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getProvider } from "@/lib/broker-providers";
import { disconnect } from "@/lib/broker-connections";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: { broker: string } }
) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }
  const provider = getProvider(params.broker);
  if (!provider) {
    return NextResponse.json({ error: "Unknown broker." }, { status: 404 });
  }
  const r = await disconnect(user.id, provider.key);
  if (!r.ok) {
    return NextResponse.json({ error: r.error ?? "failed" }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
