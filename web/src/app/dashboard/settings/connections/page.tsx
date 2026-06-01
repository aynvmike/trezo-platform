import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";
import {
  BROKER_PROVIDERS,
  CATEGORY_LABEL,
  CATEGORY_BLURB,
  providersByCategory,
  type BrokerProvider,
  type ProviderCategory
} from "@/lib/broker-providers";
import {
  listConnections,
  isTokenKeyConfigured
} from "@/lib/broker-connections";
import { BrokerRefreshStatus } from "@/components/dashboard/broker-refresh-status";

export const dynamic = "force-dynamic";

const CATEGORY_ORDER: ProviderCategory[] = ["brokerage", "crypto", "banking"];

export default async function ConnectionsPage({
  searchParams
}: {
  searchParams: { connected?: string; error?: string; detail?: string };
}) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/settings/connections");

  const connections = await listConnections(user.id);
  const keyOk = isTokenKeyConfigured();
  const grouped = providersByCategory();
  const byBroker = new Map(connections.map((c) => [c.broker, c]));

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-3xl">
      <header>
        <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
          Settings — Connections
        </p>
        <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
          Connect a broker
        </h1>
        <p className="beginner-only mt-3 max-w-2xl text-weave-600 leading-relaxed">
          One-click sign-in across {BROKER_PROVIDERS.length} providers in
          three categories. Trezo never asks for your broker password or
          API key — you sign in on the broker&apos;s own page and they
          hand Trezo a token, encrypted at rest. The same pattern works
          for every provider we add next.
        </p>
      </header>

      {/* OAuth token health — shows refresh activity + per-broker
          health badges. Renders only when there are connections to
          report on. */}
      <BrokerRefreshStatus />

      {!keyOk && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900 leading-relaxed">
          <p className="font-medium">Encryption key not set</p>
          <p className="mt-1">
            Set <code className="text-xs">TREZO_TOKENS_KEY</code> on the
            web service to a 32-byte random key (64 hex characters).
            Without it, broker connect is disabled — Trezo refuses to
            store tokens in plaintext.
          </p>
        </section>
      )}

      {searchParams.connected && (
        <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-900">
          Connected to{" "}
          <span className="font-medium">{searchParams.connected}</span>.
        </section>
      )}
      {searchParams.error && (
        <section className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-900">
          <p className="font-medium">Could not connect</p>
          <p className="mt-1">
            Reason: {searchParams.error}
            {searchParams.detail ? ` — ${searchParams.detail}` : ""}
          </p>
        </section>
      )}

      {CATEGORY_ORDER.map((cat) => (
        <section key={cat} className="space-y-3">
          <div>
            <h2 className="font-serif text-xl text-weave-800">
              {CATEGORY_LABEL[cat]}
            </h2>
            <p className="beginner-only text-sm text-weave-500 leading-relaxed">
              {CATEGORY_BLURB[cat]}
            </p>
          </div>
          <div className="space-y-3">
            {grouped[cat].map((p) => {
              const conn = byBroker.get(p.key);
              return (
                <ProviderCard
                  key={p.key}
                  provider={p}
                  connected={!!conn}
                  connectedAt={conn?.connected_at ?? null}
                  status={conn?.status ?? null}
                  keyOk={keyOk}
                />
              );
            })}
          </div>
        </section>
      ))}

      <section className="rounded-xl border border-weave-100 bg-white p-5 space-y-2">
        <h2 className="font-serif text-xl text-weave-800">
          How a connection actually works
        </h2>
        <ol className="text-sm text-weave-600 leading-relaxed list-decimal list-inside space-y-1">
          <li>You tap Connect on a provider card.</li>
          <li>
            Trezo redirects you to the provider&apos;s own login page —
            this is the broker, not us.
          </li>
          <li>
            You sign in there. The provider shows what Trezo is asking
            for (trade, read positions, etc.) and you approve.
          </li>
          <li>
            The provider hands Trezo a token tied to your account. We
            encrypt it and store the ciphertext.
          </li>
          <li>
            From then on, Trezo trades through your account — never
            ours. You can disconnect at any time and we drop the token.
          </li>
        </ol>
        <p className="beginner-only text-xs text-weave-500 leading-relaxed">
          One framework, one place tokens ever exist in cleartext (this
          server), one Connect button per provider. The cards marked
          Coming soon already have their OAuth URLs and scope ready —
          they need their provider-side OAuth app registered + the
          matching client-id env on the web service, then they flip to
          Available.
        </p>
      </section>
    </div>
  );
}

function ProviderCard({
  provider,
  connected,
  connectedAt,
  status,
  keyOk
}: {
  provider: BrokerProvider;
  connected: boolean;
  connectedAt: string | null;
  status: string | null;
  keyOk: boolean;
}) {
  const available = provider.status === "available";
  const canConnect = available && keyOk && !connected;
  return (
    <div
      className={cn(
        "rounded-xl border p-5 flex gap-4",
        connected
          ? "border-emerald-200 bg-emerald-50/60"
          : available
            ? "border-weave-100 bg-white"
            : "border-weave-100 bg-weave-50/40"
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <p className="font-medium text-weave-800">{provider.label}</p>
          <span
            className={cn(
              "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
              connected
                ? "bg-emerald-100 text-emerald-800"
                : available
                  ? "bg-treasure-100 text-treasure-700"
                  : "bg-weave-100 text-weave-500"
            )}
          >
            {connected ? "Connected" : available ? "Available" : "Coming soon"}
          </span>
        </div>
        <p className="mt-1 text-sm text-weave-600 leading-relaxed">
          {provider.blurb}
        </p>
        {connected && connectedAt && (
          <p className="mt-2 text-xs text-weave-500">
            Connected {new Date(connectedAt).toLocaleString()} · status{" "}
            {status ?? "active"}
          </p>
        )}
      </div>
      <div className="shrink-0 self-center flex flex-col gap-2">
        {connected ? (
          <form
            action={`/api/brokers/${provider.key}/disconnect`}
            method="post"
          >
            <button
              type="submit"
              className="rounded-md border border-weave-200 px-3 py-1.5 text-xs text-weave-700 hover:bg-weave-50"
            >
              Disconnect
            </button>
          </form>
        ) : (
          <a
            href={canConnect ? `/api/brokers/${provider.key}/authorize` : undefined}
            aria-disabled={!canConnect}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium text-center",
              canConnect
                ? "bg-weave-600 text-treasure-50 hover:bg-weave-700"
                : "bg-weave-100 text-weave-400 cursor-not-allowed pointer-events-none"
            )}
          >
            {available ? "Connect →" : "Soon"}
          </a>
        )}
      </div>
    </div>
  );
}
