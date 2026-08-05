/**
 * Server-only helper for the agents' rule-change proposals.
 *
 * These are NOT the same thing as the "Recent strategy proposals" feed on
 * the Strategy Engine page — that one reads agent_messages from
 * strategy_discovery / adaptive_scope. These are the written, evidence-
 * backed arguments the agents file when they think a RULE should change
 * (Mike 2026-07-27: "a way that the agents can have a way to show the
 * changes that they believe should happen"). The agents never self-apply
 * one; the document is the argument, Mike is the decision.
 *
 * Source of truth is the agents service at GET /knowledge/proposals,
 * which is backed by a JSON store and also rendered to
 * C:\Trezo\TREZO_AGENT_PROPOSALS.md.
 *
 * Returns null on miss / timeout / bad shape, never throws.
 */

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export type AgentProposal = {
  key: string;
  area: string;
  title: string;
  observation: string;
  suggestion: string;
  evidence: string;
  impact: string;
  agent: string;
  first_seen: string;
  last_seen: string;
  times_observed: number;
  status: string;
};

export type ProposalsSnapshot = {
  available: boolean;
  proposals: AgentProposal[];
  docPath: string | null;
};

function coerce(row: unknown): AgentProposal | null {
  if (!row || typeof row !== "object") return null;
  const r = row as Record<string, unknown>;
  const key = typeof r.key === "string" ? r.key : "";
  const title = typeof r.title === "string" ? r.title : "";
  if (!key || !title) return null;
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const num = (v: unknown) => {
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  return {
    key,
    title,
    area: str(r.area) || "Unspecified",
    observation: str(r.observation),
    suggestion: str(r.suggestion),
    evidence: str(r.evidence),
    impact: str(r.impact),
    agent: str(r.agent) || "system",
    first_seen: str(r.first_seen),
    last_seen: str(r.last_seen),
    times_observed: num(r.times_observed),
    status: str(r.status) || "open",
  };
}

export async function fetchProposals(): Promise<ProposalsSnapshot | null> {
  try {
    const r = await fetch(`${AGENTS_BASE}/knowledge/proposals`, {
      cache: "no-store",
      signal: AbortSignal.timeout(6000),
    });
    if (!r.ok) return null;
    const j: unknown = await r.json();
    if (!j || typeof j !== "object") return null;
    const body = j as Record<string, unknown>;
    if (body.available === false) return { available: false, proposals: [], docPath: null };
    const raw = Array.isArray(body.proposals) ? body.proposals : [];
    const proposals = raw
      .map(coerce)
      .filter((p): p is AgentProposal => p !== null)
      .sort((a, b) => b.times_observed - a.times_observed);
    const docPath =
      typeof body.doc_path === "string"
        ? body.doc_path
        : typeof body.doc === "string"
          ? body.doc
          : null;
    return { available: true, proposals, docPath };
  } catch {
    return null;
  }
}
