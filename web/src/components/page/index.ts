/**
 * Page primitives module - the Neo Obsidian template every dashboard
 * page uses. Import from "@/components/page" instead of cherry-picking
 * deep paths.
 *
 * Mike 2026-06-01: building these shared primitives so future page
 * updates don't have to relearn the pattern. Each primitive is small
 * and focused; combine them to compose any page.
 *
 * Usage pattern (see PAGE_PATTERN.md for a full walkthrough):
 *
 *   import { PageHeader, PageSection, KpiGrid, KpiTile, EmptyCard,
 *     StatusPill, Callout } from "@/components/page";
 *
 *   export default async function MyPage() {
 *     return (
 *       <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
 *         <PageHeader
 *           tag="Layer 5 — Wheel"
 *           title="Wheel (Options)"
 *           lede="One-line explanation of the page."
 *         />
 *         <KpiGrid>
 *           <KpiTile label="Open" value={count} />
 *           <KpiTile label="P&L" value={usd(pnl)} tone="good" live />
 *         </KpiGrid>
 *         <PageSection
 *           title="Open positions"
 *           description="Currently in flight."
 *         >
 *           {positions.length === 0 ? (
 *             <EmptyCard>No open positions.</EmptyCard>
 *           ) : (
 *             <PositionsTable rows={positions} />
 *           )}
 *         </PageSection>
 *       </div>
 *     );
 *   }
 */

export { PageHeader } from "./page-header";
export { PageSection } from "./page-section";
export { KpiGrid, KpiTile } from "./kpi";
export { EmptyCard } from "./empty-card";
export { StatusPill } from "./status-pill";
export { Callout } from "./callout";
