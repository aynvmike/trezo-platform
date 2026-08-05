import { fetchProposals, type AgentProposal } from "@/lib/proposals-snapshot";

export const dynamic = "force-dynamic";

function sinceLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function Field({ label, body }: { label: string; body: string }) {
  if (!body) return null;
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-wide text-weave-400">
        {label}
      </div>
      <p className="text-sm leading-relaxed text-weave-600">{body}</p>
    </div>
  );
}

function ProposalCard({ p }: { p: AgentProposal }) {
  return (
    <article className="rounded-xl border border-weave-100 bg-white p-5 space-y-4">
      <header className="space-y-2">
        <h2 className="font-serif text-lg leading-snug text-weave-800">
          {p.title}
        </h2>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-weave-500">
          <span className="rounded-full border border-weave-200 px-2 py-0.5">
            {p.area}
          </span>
          <span>raised by {p.agent}</span>
          <span aria-hidden>·</span>
          <span>
            seen {p.times_observed}
            {p.times_observed === 1 ? " time" : " times"}
            {p.first_seen ? ` since ${sinceLabel(p.first_seen)}` : ""}
          </span>
        </div>
      </header>

      <Field label="What the agents keep seeing" body={p.observation} />
      <Field label="Evidence" body={p.evidence} />
      <Field label="Why it matters" body={p.impact} />

      {p.suggestion ? (
        <div className="rounded-lg border border-treasure-200 bg-treasure-50/60 p-4 space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-wide text-weave-500">
            Proposed change
          </div>
          <p className="text-sm leading-relaxed text-weave-700">{p.suggestion}</p>
        </div>
      ) : null}

      <div className="pt-1 font-mono text-[11px] text-weave-400">{p.key}</div>
    </article>
  );
}

export default async function ProposalsPage() {
  const snap = await fetchProposals();
  const proposals = snap?.proposals ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="font-serif text-2xl text-weave-800">
          What the agents would change
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-weave-500">
          When the agents notice a rule that keeps costing them — a floor that
          refuses too many good trades, a lane that has earned more room, a
          measurement with a blind spot — they write the argument down here
          instead of changing it themselves. Nothing on this page has been
          applied. Each one is a decision waiting for you.
        </p>
      </div>

      {snap === null ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-weave-50/40 p-5 text-sm leading-relaxed text-weave-500">
          Could not reach the agents service to load proposals. If the engine
          is stopped, start it and reload — the proposals are stored on disk
          and nothing is lost while it is down.
        </div>
      ) : proposals.length === 0 ? (
        <div className="rounded-xl border border-dashed border-weave-200 bg-weave-50/40 p-5 text-sm leading-relaxed text-weave-500">
          Nothing proposed yet. The detectors run on the daily watchdog gate:
          they look for lanes with a strong or poor record, refusals that
          clustered just under a floor, and caps that keep being hit. An empty
          page means the agents currently have no evidence-backed argument for
          changing a rule.
        </div>
      ) : (
        <>
          <div className="text-sm text-weave-500">
            {proposals.length} open{" "}
            {proposals.length === 1 ? "proposal" : "proposals"}, strongest
            evidence first.
          </div>
          <div className="space-y-4">
            {proposals.map((p) => (
              <ProposalCard key={p.key} p={p} />
            ))}
          </div>
        </>
      )}

      <p className="border-t border-weave-100 pt-4 text-xs leading-relaxed text-weave-400">
        The agents never apply a rule change on their own. This page is the
        argument; you are the decision. The same content is written to
        TREZO_AGENT_PROPOSALS.md in your Trezo folder after every detection
        pass.
      </p>
    </div>
  );
}
