# Skills & Plugins Playbook

A portable reference to the skill and plugin toolkit available in this
workspace. Copy this file into any future project so the assistant (Nova)
can pick the right tool fast — without re-deriving workflows, and without
re-reading project history.

**Purpose:** save tokens and development time on future work by carrying a
known toolkit forward.
**Safe to share:** this document contains no keys, no credentials, no
project data, and no proprietary logic. See "What never goes in here" at
the end.

_Last updated: 2026-05-22, during the Trezo build._

---

## Why a playbook saves tokens and time

A "skill" or "plugin" is a pre-packaged workflow. When the assistant
invokes one, it loads a tested set of steps instead of inventing them in
the conversation. That means:

- **Fewer tokens** — the workflow is not re-explained every project.
- **Less time** — no trial-and-error rediscovering the right approach.
- **Consistency** — the same job is done the same way each time.

This playbook is the index. It says *what exists* and *when to reach for
it*, so the first move on a new project is a lookup, not a guess.

---

## The toolkit, grouped by job

Each plugin below bundles several skills. Reach for the group that matches
the work in front of you.

### Software & product

- **engineering** — the core kit for any software build. Skills:
  architecture (decision records), system-design, code-review, debug,
  testing-strategy, tech-debt, deploy-checklist, incident-response,
  documentation, standup.
- **product-management** — write-spec / PRDs, roadmap-update,
  sprint-planning, competitive-brief, metrics-review, stakeholder-update,
  synthesize-research, brainstorm.
- **product-tracking-skills** — analytics instrumentation: model the
  product, audit current tracking, design a tracking plan, generate an
  SDK implementation guide, write the tracking code, instrument new
  features as they ship.
- **figma** — generate designs/components from code, build design-system
  libraries, create diagrams, maintain Code Connect mappings.

### Data & analytics

- **data** — analyze datasets, write/optimize SQL, explore and profile
  data, statistical analysis, build HTML dashboards, create
  visualizations, validate an analysis before sharing.

### Documents & file output (core skills)

- **docx / pdf / pptx / xlsx** — create and edit Word docs, PDFs, slide
  decks, and spreadsheets. Use after the research/content is ready.
- **pdf-viewer** — open a PDF in an interactive viewer to annotate,
  highlight, fill form fields, or place a signature.

### Finance & markets

- **finance** — financial statements, journal entries, reconciliation,
  variance analysis, month-end close, SOX testing, audit support.
- **daloopa** — multi-tab Excel models, DCF, comps, earnings analysis,
  tear sheets (uses the Daloopa data connector).
- **lseg** — fixed income, FX carry, options vol, swap curves, macro/rates
  dashboards, equity research (uses the LSEG data connector).
- **sp-global** — Capital IQ-backed Excel models, company tear sheets,
  earnings previews, funding digests.

### Go-to-market

- **sales** — account research, call prep, call summaries, outreach
  drafting, pipeline review, forecasting, competitive battlecards.
- **common-room** — account/contact research, prospecting, outreach, and
  call prep driven by the Common Room signal connector.
- **marketing** — campaign plans, content creation, email sequences, SEO
  audits, performance reports, brand review.
- **brand-voice** — discover brand materials, generate voice guidelines,
  enforce brand voice on new content.

### Operations & business

- **operations** — capacity planning, process docs, runbooks, risk
  assessment, change requests, status reports, vendor review,
  compliance tracking.
- **small-business** — a full owner-operator suite: cash-flow forecast,
  month-end close, lead triage, invoice chasing, payroll planning,
  tax-season prep, marketing campaigns.
- **customer-support** — ticket triage, response drafting, escalation
  packaging, KB articles, customer research.
- **legal** — contract review, NDA triage, compliance checks, legal risk
  assessment, vendor checks, signature routing.

### Web data

- **brightdata-plugin** — live web scraping, search (SERP), structured
  data feeds from 40+ platforms, competitive intelligence, SEO audits,
  custom scraper building (uses the Bright Data connector/CLI).

### Building & meta

- **skill-creator** — create, edit, and test new skills.
- **mcp-builder** — build MCP servers to connect new external services.
- **web-artifacts-builder** — build complex multi-component HTML artifacts.

---

## Starter kit by project type

The first question on a new project: what kind of project is it? Then load
that row.

| Project type            | Reach for first                                              |
|-------------------------|--------------------------------------------------------------|
| Software / app build    | engineering, product-management, product-tracking-skills     |
| Data analysis / reporting | data, xlsx, pdf                                            |
| Financial analysis      | finance, daloopa, lseg, sp-global, xlsx                      |
| Sales / GTM             | sales, common-room, marketing, brand-voice                   |
| Operations / business   | operations, small-business, customer-support, legal          |
| Research / web data     | brightdata-plugin, data                                      |
| Design / UI             | figma, web-artifacts-builder                                 |
| Any deliverable doc     | docx, pdf, pptx, xlsx (always: research first, format last)  |

---

## What was used on the Trezo build

Trezo is a multi-phase software product, so the **engineering** group is
the natural shell to reuse for the next software project — architecture
decisions, system design, code review, debugging, testing strategy, deploy
checklists, and documentation all map directly. **product-management**
(specs and roadmap) and **product-tracking-skills** (analytics
instrumentation) are the companion sets.

Much of the Trezo build was hands-on coding written directly to files
rather than routed through a skill — that is normal for a long custom
build. The value of this playbook is the *next* project: starting from a
known toolkit instead of a blank page.

---

## Reusable working patterns from the Trezo build

These are practices, not code — fully portable, no secrets, and the real
token/time savers:

1. **Phase-by-phase delivery.** Break the build into numbered phases.
   Finish and verify one before starting the next. Never skip ahead.
2. **Checkpoint files.** At the end of each phase, write a short
   checkpoint: what was done, what is pending, what is next. Resuming then
   costs one file read instead of re-deriving context.
3. **Task list discipline.** Keep an explicit task list. Mark items
   in-progress and completed as work moves. It survives interruptions.
4. **Verify after every write.** After generating a file, check it —
   balanced braces/parentheses, no stray null bytes, code parses. Catch
   corruption immediately, not three steps later.
5. **A persistent memory file.** Keep notes on preferences, decisions, and
   project state so the next session starts informed.
6. **Plain-language copy.** User-facing text explains the *why* in
   everyday words, not just the *what*. It makes a product trustworthy.
7. **Research first, format last.** Gather all facts and content before
   invoking a document skill (docx/pptx/xlsx/pdf). The skill builds the
   deliverable; it does not do the thinking.

---

## How to use this file in a new project

1. Drop this file into the new project's working folder.
2. At the start, tell the assistant: "Check the Skills & Plugins Playbook."
3. The assistant matches the project type to the "Starter kit" table and
   loads the right group — no rediscovery needed.
4. Update the "Last updated" date and add any new plugin or pattern you
   pick up, so the playbook compounds over time.

---

## What never goes in here

To keep this file safe to carry anywhere, it must never contain:

- API keys, secret tokens, passwords, or connection strings.
- Contents of any `.env` file.
- Database project IDs, hostnames, or URLs.
- Proprietary algorithms, trading rules, or business logic.
- Customer, user, or minor-account personal data.
- Internal absolute file paths from a specific project.

This playbook describes *which tools exist and when to use them* — never
the private contents of the work they were used on.
