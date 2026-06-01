import { createClient } from "@/lib/supabase/server";

/**
 * BrokerRefreshStatus — surfaces the latest 5 OAuth refresh attempts
 * across the user's broker connections, so Mike can verify the cron
 * job is running and see what failed if anything did.
 *
 * Server component. Reads `broker_token_refresh_log` (RLS-restricted
 * to the signed-in user) and `broker_connections` (for the per-row
 * `consecutive_refresh_failures` + `last_refresh_at` summary).
 */
export async function BrokerRefreshStatus() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const [{ data: logs }, { data: conns }] = await Promise.all([
    supabase
      .from("broker_token_refresh_log")
      .select("broker, status, note, ran_at, new_expires_at")
      .eq("user_id", user.id)
      .order("ran_at", { ascending: false })
      .limit(5),
    supabase
      .from("broker_connections")
      .select(
        "broker, status, consecutive_refresh_failures, last_refresh_at, expires_at"
      )
      .eq("user_id", user.id),
  ]);

  const haveAny = (logs && logs.length > 0) || (conns && conns.length > 0);
  if (!haveAny) return null;

  return (
    <section className="rounded-xl border border-weave-100 bg-white p-4 space-y-3">
      <div>
        <h2 className="font-medium text-weave-800">OAuth token health</h2>
        <p className="text-xs text-weave-500 leading-relaxed mt-0.5">
          The agents service kicks the refresh route every 15 minutes.
          Tokens expiring in the next hour get rolled forward
          automatically — you should never have to reconnect a broker
          mid-session unless something broke 3 times in a row.
        </p>
      </div>

      {conns && conns.length > 0 ? (
        <div className="grid sm:grid-cols-2 gap-2">
          {conns.map((c) => {
            const fails = c.consecutive_refresh_failures ?? 0;
            const tone =
              c.status === "expired" || fails >= 3
                ? "text-red-700 border-red-200 bg-red-50"
                : fails > 0
                ? "text-amber-800 border-amber-200 bg-amber-50"
                : "text-emerald-800 border-emerald-200 bg-emerald-50";
            return (
              <div
                key={c.broker}
                className={`rounded-lg border px-3 py-2 ${tone}`}
              >
                <p className="font-mono text-xs uppercase tracking-widest">
                  {c.broker}
                </p>
                <p className="text-sm font-medium">
                  {c.status === "expired"
                    ? "Reconnect needed"
                    : fails > 0
                    ? `${fails} recent failure${fails === 1 ? "" : "s"}`
                    : "Healthy"}
                </p>
                <p className="text-[11px] mt-0.5 leading-relaxed">
                  {c.last_refresh_at
                    ? `Last check: ${new Date(c.last_refresh_at).toLocaleString()}`
                    : "No refresh attempts yet"}
                  {c.expires_at ? (
                    <>
                      {" · "}
                      Expires {new Date(c.expires_at).toLocaleString()}
                    </>
                  ) : (
                    " · Long-lived token"
                  )}
                </p>
              </div>
            );
          })}
        </div>
      ) : null}

      {logs && logs.length > 0 ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-weave-600 hover:text-weave-800">
            Recent attempts ({logs.length})
          </summary>
          <ul className="mt-2 divide-y divide-weave-50 -mb-1">
            {logs.map((l, i) => (
              <li
                key={i}
                className="py-1.5 flex items-baseline justify-between gap-3"
              >
                <span className="font-mono text-weave-700">
                  {l.broker}
                </span>
                <span
                  className={
                    l.status === "refreshed"
                      ? "text-emerald-700"
                      : l.status === "skipped"
                      ? "text-weave-500"
                      : "text-red-700"
                  }
                >
                  {l.status}
                </span>
                <span className="flex-1 text-weave-500 text-[11px] truncate">
                  {l.note ?? ""}
                </span>
                <span className="text-weave-400 text-[10px] tabular-nums">
                  {new Date(l.ran_at).toLocaleTimeString()}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
