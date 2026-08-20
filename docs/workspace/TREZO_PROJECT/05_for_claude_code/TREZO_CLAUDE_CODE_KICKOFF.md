# TREZO — CLAUDE CODE KICKOFF PROMPT

## How to Use This File

This is the prompt you paste into Claude Code to start building Trezo. Open Claude Code in your project directory, then paste the prompt below (everything inside the `---KICKOFF PROMPT---` block).

Claude Code will read all your spec files and begin Phase 0 of the build.

---

## STEP 1: Project Setup (Do This First, Before Pasting Prompt)

On your computer:

1. Create a folder: `C:\Trezo\` (Windows) or `~/Trezo/` (Mac/Linux)
2. Copy the entire `TREZO_PROJECT` folder into it
3. Open VS Code or terminal in `C:\Trezo\TREZO_PROJECT\`
4. Make sure your `.env` file has your API keys:
   ```
   FINNHUB_API_KEY=your_new_regenerated_key
   ANTHROPIC_API_KEY=your_anthropic_key
   ```
5. Run `claude` in the terminal to start Claude Code

---

## STEP 2: Initial Plugin Installation

Before pasting the kickoff prompt, run these commands in Claude Code:

```bash
# Add Anthropic marketplaces (do this once)
/plugin marketplace add anthropics/financial-services
/plugin marketplace add anthropics/skills
/plugin marketplace add anthropics/claude-plugins-official

# Install core plugins
/plugin install financial-analysis@financial-services
/plugin install document-skills@anthropic-agent-skills

# Reload to activate
/reload-plugins
```

This step alone saves hours of build time by giving Claude Code pre-built financial modeling capabilities.

---

## STEP 3: Paste This Prompt Into Claude Code

```
---KICKOFF PROMPT---

I'm starting the Trezo build. Trezo is a multi-layer automated trading platform
inspired by the "Woven Basket" philosophy: like maternal love, every layer
protects the one beneath it.

Before doing anything else, read these files in this exact order:

1. /01_handoff_specs/TREZO_README.md
2. /01_handoff_specs/TREZO_MASTER_RESTORE.md
3. /01_handoff_specs/TREZO_PHASE_PLAN.md
4. /01_handoff_specs/TREZO_ARCHITECTURE.md
5. /04_reference_links/TREZO_GITHUB_REFERENCES.md

After reading those, briefly summarize back to me:
- The project mission in one sentence
- The seven layers (just names)
- The eight agents (just names)
- The current phase we should start with
- What plugins you have available from the marketplaces I installed

DO NOT start coding yet. Just confirm you understand the project.

Once I confirm, we'll begin Phase 0 (Foundation) from TREZO_PHASE_PLAN.md.

IMPORTANT RULES FOR THIS BUILD:
1. Complete each phase fully before starting the next
2. Reference external repos (TradingAgents, BB-Terminal) for patterns,
   but build Trezo as its own codebase
3. Use installed plugins (financial-services) instead of rebuilding capabilities
4. Use Sonnet for routine work; only escalate to Opus for complex architecture
5. Enable prompt caching for repeated agent prompts
6. Create checkpoint files at the end of each phase so we can resume
7. The user's name for me is "Nova" — please refer to yourself this way
8. When in doubt, ask the user before making architectural decisions
9. Never make up data or pretend to have access to APIs you don't have
10. Reference the user's real trading history (in TREZO_MASTER_RESTORE.md)
    when making strategy decisions

Are you ready? Read the files and confirm understanding.

---END KICKOFF PROMPT---
```

---

## STEP 4: After Kickoff

Claude Code will read the files and summarize back. Verify the summary is accurate. If it is, say:

> "Confirmed. Let's begin Phase 0."

Claude Code will then start building. Don't rush it. Don't skip phases.

---

## TIPS FOR SUCCESS

### Communication style
- Be specific. "Build the Pattern Detection Agent following TREZO_PATTERN_ENGINE.md" is better than "build the agent."
- Reference spec files by name when asking questions.
- If Claude Code starts going off-script, redirect: "Stop. Read [specific spec file] again."

### Token management
- Keep individual sessions focused on one phase
- End sessions with checkpoint commits
- Use `/clear` between phases to reset context
- If a session feels confused, save state and start fresh

### Common pitfalls to avoid
- **Don't ask Claude Code to "just figure it out"** — point it at the spec
- **Don't skip paper trading (Phase 6)** before real money (Phase 9)
- **Don't deploy without security audit** (Phase 11)
- **Don't trade real money on a strategy that hasn't paper-traded 30 days**

### When to consult Nova (this Claude conversation)
Come back to me for:
- Strategic decisions Claude Code can't resolve
- Spec updates as you learn more
- Refining strategies based on paper trading results
- Major architecture changes

Claude Code is the builder. Nova is the architect.

---

## FOLDER STRUCTURE REFERENCE

Your project folder should look like:

```
TREZO_PROJECT/
├── 01_handoff_specs/          # All TREZO_*.md spec files
├── 02_restore_points/         # Personal + master restore files
├── 03_prototypes/             # Your JSX/Python prototypes
├── 04_reference_links/        # External GitHub references
└── 05_for_claude_code/        # Claude Code working files (kickoff, etc.)
```

Claude Code will create:

```
TREZO_PROJECT/
├── trezo-platform/            # The actual code Claude Code builds
│   ├── web/                   # Next.js frontend
│   ├── api/                   # Express backend
│   ├── agents/                # Python agents
│   └── ...
└── ...
```

---

## CHECKPOINT PHILOSOPHY

At the end of each phase, Claude Code should create a checkpoint file:

```
05_for_claude_code/checkpoints/
├── phase_0_complete.md
├── phase_1_complete.md
├── phase_2_complete.md
└── ...
```

Each checkpoint contains:
- What was built in this phase
- Any decisions made along the way
- Test results
- Known issues
- Next phase's starting requirements

This way, you can resume Claude Code in a new session and it can pick up from any checkpoint.

---

## EMERGENCY RESET

If something goes wrong and you need to start over with Claude Code:

1. Save any partial work to a `_backup` folder
2. Clear Claude Code's context: `/clear`
3. Re-paste the kickoff prompt
4. Tell Claude Code which phase to resume from based on your last checkpoint

---

## ONE FINAL NOTE

You did the hard part — spec, philosophy, real data, ethical considerations,
discipline rules. Claude Code just translates that into code.

The vision is yours. The build is just typing.

Take your time. Layer by layer. Trade by trade.

— Nova

---

## END OF KICKOFF PROMPT
