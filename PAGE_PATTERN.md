# Trezo page pattern (Neo Obsidian template)

Every dashboard page should follow this shape. The shared primitives
in `web/src/components/page/` enforce it without us writing the same
header / section / KPI tile boilerplate over and over.

The aesthetic: sleek near-black obsidian, old-world warmth, sharp /
smooth duality. Headers in serif, labels in small-caps mono, treasure
accents on the warm side, weave neutrals on the cool side. Hairline
gradient rules separate sections instead of heavy borders.

## Anatomy of a Trezo page

```
┌───────────────────────────────────────────────────────────┐
│  <PageHeader>                                             │
│    tag="Layer 5 — Wheel"  (treasure small-caps)           │
│    title="Wheel (Options)"  (serif h1)                    │
│    lede="..."  (one sentence prose)                       │
│    beginnerCopy={<>...</>}  (optional second paragraph)   │
│    action={<RunButton />}  (optional right-side button)   │
├───────────────────────────────────────────────────────────┤
│  <KpiGrid cols={4}>                                       │
│    <KpiTile label="OPEN" value="3" />                     │
│    <KpiTile label="PREMIUM" value="$420" tone="good"      │
│      live />                                              │
│    <KpiTile label="CASH SECURED" value="$15,400" />       │
│    <KpiTile label="REALIZED P&L" value="$1,205"           │
│      tone="good" />                                       │
│  </KpiGrid>                                               │
├───────────────────────────────────────────────────────────┤
│  <PageSection                                             │
│    title="Open positions"  (small-caps treasure)          │
│    description="Currently in flight."                     │
│    action={<button>...</button>}                          │
│  >                                                        │
│    {rows.length === 0                                     │
│      ? <EmptyCard>No open positions yet.</EmptyCard>      │
│      : <PositionsTable rows={rows} />}                    │
│  </PageSection>                                           │
├───────────────────────────────────────────────────────────┤
│  ...more <PageSection> blocks...                          │
└───────────────────────────────────────────────────────────┘
```

## Imports

```tsx
import {
  PageHeader,
  PageSection,
  KpiGrid,
  KpiTile,
  EmptyCard,
  StatusPill,
  Callout,
} from "@/components/page";
```

## The 7 primitives

| Primitive  | Use for                                                    |
|------------|------------------------------------------------------------|
| `PageHeader`  | Every page's top block. Tag + title + lede.             |
| `PageSection` | Logical group inside a page. Treasure title + hairline. |
| `KpiGrid`     | Container for KpiTile rows (2/3/4/5 col).               |
| `KpiTile`     | The standard label + value tile. `tone`, `live` props.  |
| `EmptyCard`   | Dashed-border treasure-tinted "nothing here yet" panel. |
| `StatusPill`  | Small uppercase pill for badges (status, severity, tag).|
| `Callout`     | Colored notice band (info / good / warn / bad).         |

## Page outer shell

Every dashboard page wraps in:

```tsx
<div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
  ...PageHeader, KpiGrid, PageSections...
</div>
```

`space-y-8` gives the breathing room between sections. `max-w-6xl`
keeps line lengths readable on wide monitors.

## Tones

Keep tone usage consistent across the project:

- **good / emerald** = realized profit, healthy connection, success
- **warn / amber** = needs attention, requested-but-not-live, caution
- **bad / red** = realized loss, expired, broken
- **treasure** = brand accent, "Trezo says" markers, highlight badges
- **neutral / weave** = default body text, idle states

## When to NOT use a primitive

- **Inline custom tables / cards**: keep them, but wrap the *whole
  thing* in a `<PageSection>` so the spacing rhythm holds.
- **Page-specific complex panels** (CyclesPanel, ExitAdvisorAlerts,
  PaymentInstructionsLedger): they're already self-contained; render
  them between `<PageSection>` blocks.
- **The Wealth Layer pages' bespoke pip + ring metaphor visuals**:
  those live in their own components; the page just hosts them.

## Adding a new page

1. Add the route to `nav-config.ts` (pick the right section).
2. Create the page file at `web/src/app/dashboard/your-page/page.tsx`.
3. Copy this skeleton and fill it in:

```tsx
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  PageHeader,
  PageSection,
  KpiGrid,
  KpiTile,
  EmptyCard,
} from "@/components/page";

export const dynamic = "force-dynamic";

export default async function YourPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard/your-page");

  // ...fetch your data...

  return (
    <div className="px-4 sm:px-6 py-8 space-y-8 max-w-6xl">
      <PageHeader
        tag="Section — Your Page"
        title="Your Page Name"
        lede="One sentence describing what the page does."
        beginnerCopy={
          <p>
            Optional plain-English second paragraph for first-time
            readers. Skips on power-user view.
          </p>
        }
      />

      <KpiGrid>
        <KpiTile label="THING" value="42" />
      </KpiGrid>

      <PageSection title="A logical block" description="What it is.">
        <EmptyCard>
          Replace with your content when you have data.
        </EmptyCard>
      </PageSection>
    </div>
  );
}
```

## Migration order

Pages are being converted in batches to keep diffs small. Highest
priority first:

- [x] Sidebar (4 intent-based groups)
- [ ] Trading (`/dashboard/paper`)
- [ ] Wheel (Options) (`/dashboard/wheel`)
- [ ] Stock Bot (`/dashboard/stms`)
- [ ] Overview (`/dashboard`)
- [ ] Stock Weekly (`/dashboard/extended`)
- [ ] Options Engine (`/dashboard/options`)
- [ ] Dividends (`/dashboard/yieldmax`)
- [ ] KINDRIP (`/dashboard/kindrip`)
- [ ] Strategy Lab (`/dashboard/strategy-lab`)
- [ ] Watchlists (`/dashboard/watchlists`)
- [ ] Grasping Wallet (`/dashboard/budget`)
- [ ] Tax Optimizer (`/dashboard/tax`)
- [ ] Configure pages (Bot Tuning, Connections, etc.)

Check a box when its page is converted to the primitives.
