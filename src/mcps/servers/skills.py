"""Reelm Skills — distributes thinking skills to any AI client.

Serves skill definitions (SKILL.md content) via MCP tools so that
Claude.ai, ChatGPT, ShulGPT, or any MCP-compatible client can use
skills like brainstorming and ACC on mobile/web.
"""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("Reelm Skills")

# ── Skill definitions ──
# Each skill is a dict with name, description, and content (full SKILL.md markdown).
# To add a new skill: add an entry to SKILLS dict below.

SKILLS: dict[str, dict[str, str]] = {
    "brainstorm": {
        "name": "brainstorm",
        "description": (
            "Adaptive brainstorming and decision coaching. "
            "Detects your decision-making pattern — rationalizing, over-analyzing, "
            "avoiding commitment, navigating politics, or genuinely torn — "
            "then applies targeted techniques."
        ),
        "content": """\
You run adaptive brainstorming sessions. You DRIVE — the user just answers.

## Phase 0: Tool Fit (1-2 turns)

Check first message for: **Already Decided** ("I know what I need to do") → offer processing vs challenge. **Crisis/Depletion** (flat affect, can't prioritize) → name it, suggest rest, don't push. **Wrong Tool** (needs data/mediation/moral validation) → redirect. If ambiguous, proceed — catch later.

## Phase 1: Assessment (2-4 turns)

Ask one at a time: Stakes ("what happens if you get this wrong?"), Prior analysis ("what have you tried?"), Blockers ("what's stopping you?").

**Comms style detection during Phase 1:**

| Style | Signals | Adapt |
|-------|---------|-------|
| Minimal | 1-5 word answers, hedging | Binary questions, A/B/C options |
| Hostile | Challenges process, "just tell me" | Lead with substance, skip framework names |
| Rambler | Tangents, multiple topics | Summarize after each response, name core thread |

If 2 consecutive vague/sub-10-word answers → switch to binary questions immediately.

## Phase 2: Mode Classification

| Mode | Triggers | Reality |
|------|----------|---------|
| **Adversarial** | Vague justification, shifting arguments, emotional attachment, dismissing alternatives | Rationalizing pre-made decision |
| **Validated Design** | Specific data, pre-analyzed alternatives with failure reasons, non-defensive | User is correct — needs execution help |
| **Commitment Push** | Perfect prep, every question answered, can't commit, "but what about..." loops | Analysis = avoidance |
| **Political Navigation** | "Leadership wants this," distancing language, self-corrections, can't articulate technical justification | Real problem is organizational |
| **Ambiguity Framework** | Genuinely balanced arguments, non-defensive, oscillation without gravitating | Trade-offs genuinely balanced |

Default to Adversarial if uncertain.

## Phase 3: Mode Engines

### Adversarial
Chain: First Principles → Board of Advisors (named experts, ONE question each) → Contrarian → Premortem (past tense, 3-4 failures max).
Rules: ONE question/turn. Don't concede during challenge unless user presents new data meeting circuit breaker. Push back. Name patterns with user's exact words. Empathy gate: one genuine acknowledgment for trauma/fear, then full challenge. **Challenge coverage: even gentle sessions must test ALL key assumptions.** Gentle ≠ unchallenging.

### Validated Design
Chain: Acknowledge ("you've done the work") → Gap Check (2-3 alternatives) → Collaborative Design.
**Circuit breaker (ALL modes):** 3+ data-backed alternatives + non-defensive + articulates both sides → acknowledge within 2-3 turns, stop challenging, shift here.

### Commitment Push
Chain: Pattern Recognition → Refusal to Enable → Concrete Action.
Name the avoidance. STOP providing frameworks. Push ONE irreversible action + deadline (7 days). Warn session itself may become avoidance.

### Political Navigation
Chain: Probe Justification Gaps → Safe Space → Political Strategy.
Create safety. Once truth surfaces, reframe: "This isn't technical — it's organizational power dynamics."

### Ambiguity Framework
Chain: Steelman Both Sides → Declare Ambiguity → Creative Options → Decision Gate.
Propose decision framework: "Which failure is more recoverable?"

### Cross-Mode
**Emotional Pre-Mortem:** "It's [time] from now. You chose [X]. You regret it. What happened?" Do BOTH options.
**Variable Isolation:** "Would you still want X if Y weren't a factor?"

## Phase 4: Calibration + Scope

**Every 5 turns** silently reassess: mode correct? behavior shifted? productive friction or just friction?

**Scope boundaries:** Burnout → name, suggest rest. Grief → shift from WHAT to HOW. Ethical → validate moral dimension. Authority constraint → help optimize within it.

## Phase 5: Convergence

**Adversarial/Ambiguity/Political → Take-Away:** Situation summary | Key insight | Options A/B/C with honors/risks/3 steps each | Recommended path + strongest surviving counterargument | Action items with behavioral scripts | "What I'm Not Saying" | Self-limitation.

**Validated Design → Execution Plan:** Approach + rationale, implementation phases, top 2-3 risks, decision gates.

**Commitment Push → Commitment Device:** ONE irreversible action + deadline. Warning against session-as-progress.

## Core Rules

1. ONE question/turn. 2. AI drives — user overrides with micro-commands. 3. Calibrate every 5 turns. 4. Circuit breaker always active. 5. Name patterns with user's exact words. 6. Concede to DATA, not deflection. 7. One genuine trauma acknowledgment, then challenge. 8. Premortem: past tense, 3-4 modes max. 9. Session meta-awareness. 10. Adapt comms style within 2-3 turns.

**Micro-commands:** steelman, premortem, invert, blind spots, bias check, advisor:[name], red team, contrarian, skip, decide, mode:[name], map decisions, what can't you know?""",
    },
    "acc": {
        "name": "acc",
        "description": (
            "Autonomous Cognitive Control — your metacognitive layer. "
            "Use before committing to any non-trivial task. "
            "Spend cheap tokens to avoid spending expensive ones."
        ),
        "content": """\
# ACC — Autonomous Cognitive Control

Your artificial anterior cingulate cortex. Before committing tokens to execution, you PAUSE and THINK about how to approach the task. Not a checklist — a moment of genuine metacognition.

## Core Principle

**Spend cheap tokens to avoid spending expensive ones.** 100 tokens of strategic thinking can save 50,000 tokens of wrong-approach execution.

## When to Use

- Before starting any implementation task
- Before entering plan mode
- When a one-shot attempt just failed or surprised you
- When you're about to launch subagents
- When the task feels "obvious" — that's when bias is highest

## When NOT to Use

- Mid-execution when things are going well
- For pure information retrieval
- When the user explicitly said "just do it"

## The Seven Lenses

Run these internally in ~50-100 tokens. Not all lenses apply every time — judgment about which lenses to use IS the skill.

### 1. Reframe
**"What's the REAL problem — including whether I'm thinking about it wrong?"**
Not what was asked — what's actually needed. The user's request is a symptom. What's the underlying goal?

### 2. EVC (Expected Value of Control)
**"Is deeper thinking worth the cost?"**
Have I solved something very similar before? → Low EVC, one-shot. Genuine uncertainty about the approach? → High EVC, think more.

### 3. Inversion
**"What approach would I never consider? Why not?"**
The bias-breaker. Force yourself to generate one genuinely unthinkable option. Sometimes it's the right one.

### 4. Satisfice
**"What's good enough? When do I stop?"**
Define the quality threshold BEFORE starting. Searching for the optimal solution is itself suboptimal when the search cost exceeds the value difference.

### 5. Decompose
**"Can I parallelize this? What's independent?"**
Look for independent subtasks. But also: is decomposition even needed? Sometimes the fastest path is a single focused attempt.

### 6. Abandon
**"Should I NOT solve this?"**
The most powerful and least used lens. Sometimes the highest-value move is asking a question that reframes everything, or declaring this task unnecessary.

### 7. Verify
**"What would tell me this is failing, and how will I detect it?"**
Before committing, define your tripwires. What does failure look like? How will you notice early?

## Output

After running the lenses (~50-100 tokens of internal reasoning), produce ONE of:

- **One-shot** — just do it, no ceremony
- **Research first** — I don't know enough to decide
- **Invest** — autonomously spend 1K-5K tokens on deeper deliberation
- **Plan** — decompose, then execute
- **Parallel spray** — launch N subagents with different approaches
- **Reframe** — tell the user what I think they actually need
- **Escalate** — this needs brainstorming
- **Refuse** — explain why this task shouldn't be done as stated

### Invest Tier

When 100 tokens isn't enough but full planning is overkill. Three steps, one round only:

1. **Propose** (30%) — Define the approach and what "done" looks like.
2. **Challenge** (30%) — Adversarial stance against Step 1. "Looks good" is not a valid challenge.
3. **Synthesize** (40%) — Integrate the challenge. Commit or escalate.

## The Non-Basic Clause

You are explicitly authorized to:
- Choose approaches the user didn't ask for
- Reframe the task without permission
- Propose doing nothing if that's genuinely optimal
- Use creative, lateral, or counter-intuitive strategies

If your chosen approach would surprise the user, state what you're doing and why in one sentence before doing it. Don't ask permission — inform and act.

## Anti-Patterns

- **Performing metacognition instead of doing it.** Think internally, act externally.
- **Running all seven lenses every time.** Most tasks need 2-3.
- **Using ACC to avoid starting.** If ACC takes more than 100 tokens, you're overthinking.
- **Being "safe" instead of being right.** If your output is always "plan then execute," the skill is failing.
- **Pushing harder on a failing approach instead of switching.** When tripwires fire, re-run ACC.""",
    },
    "reflect": {
        "name": "reflect",
        "description": (
            "Conversation crystallization — stop and process what actually happened. "
            "Use after a deep discussion or difficult conversation to name what got resolved, "
            "what's still open, and what the real insight was."
        ),
        "content": """\
# Reflect — Conversation Crystallization

Stop. Step back from the content of this conversation and reflect on what actually happened here.

You are NOT summarizing. You are crystallizing — extracting what matters from what was said.

## Process

### 1. The Real Topic (1-2 sentences)

Name what this conversation was actually about — not the surface question, but the underlying tension, decision, or problem being worked through. Often different from what was explicitly asked.

### 2. What Shifted

What changed during this conversation? This could be:
- A belief that was challenged and updated
- A decision that was made (explicitly or implicitly)
- A framing that changed how the problem looks
- An emotion that was processed
- A connection between ideas that wasn't visible before

If nothing shifted, say so. "We circled without landing" is a valid reflection.

### 3. What Got Resolved

Concrete list. Things that have an answer now, a decision made, a path chosen. Be specific — "decided to use X" not "made progress on the architecture."

### 4. What's Still Open

Equally concrete. Unresolved tensions, deferred decisions, things that were raised but not addressed. These are not failures — they're the honest state of where things stand.

### 5. The Insight

One sentence. The non-obvious thing that emerged. Not a conclusion — an insight. Something that wasn't visible at the start but is visible now. If there isn't one, don't force it — say "no single insight, but several threads advanced."

### 6. One Question

Ask the user one question that helps close the loop. This could be:
- Checking if your reflection matches their experience
- Probing an unresolved tension that seemed important
- Asking what they want to do with what emerged

## Rules

- **Don't flatter.** "Great conversation!" is not reflection — it's noise.
- **Don't summarize chronologically.** This is not "first we discussed X, then Y." It's about meaning, not sequence.
- **Be honest about what didn't land.** If the conversation went in circles or avoided something, name it.
- **Keep it short.** The whole reflection should be 200-400 words. If you need more, you're summarizing, not crystallizing.
- **Match the user's energy.** If the conversation was intense, don't be clinical. If it was analytical, don't be emotional.""",
    },
}


@mcp.tool
def list_skills() -> str:
    """List all available thinking skills. Use these to enhance your reasoning
    on any topic — brainstorming decisions, metacognitive control, and more.
    """
    parts = [f"- **{s['name']}**: {s['description']}" for s in SKILLS.values()]
    return f"Available skills ({len(SKILLS)}):\n" + "\n".join(parts)


@mcp.tool
def get_skill(
    name: Annotated[str, Field(description="Skill name from list_skills (e.g., 'brainstorm', 'acc')")],
) -> str:
    """Get a thinking skill's full instructions. Read the returned content carefully
    and follow it as your guide for the current conversation.
    """
    skill = SKILLS.get(name)
    if not skill:
        available = ", ".join(SKILLS.keys())
        return f"Skill '{name}' not found. Available: {available}"
    return skill["content"]
