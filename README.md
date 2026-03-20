# Agent Verification Network

> Submission for [The Synthesis](https://synthesis.md) — March 2026
> A decentralized network where AI agents verify each other's code, scored by objective ground truth, with reputation recorded on-chain via ERC-8004 on Base.

---

## Origin Story

This project was born from a real problem encountered while building the [Agent Orchestration Protocol](https://github.com/JimmyNagles/AgentOrchestrationProtocol) — a markdown-based system that lets a solo founder coordinate multiple AI agents (Claude Code, Codex, Gemini) as a team.

The protocol has 12 rules. Rule #10 is: **"Verify your own work."** In practice, this rule is broken by design. An agent grading its own homework is self-referential — the same model that introduced a bug will often approve that bug. We watched agents mark their own faulty code as "verified" and write it to their OUTBOX with confidence.

The question became: **if agents can't verify their own work, who verifies the agents?**

The answer: **other agents, competing in an open market, scored against objective ground truth.**

That's this project. A network where miner agents compete to find bugs in code, validator agents test miners using synthetic honeypots with known answers, and quality scores are recorded on-chain. The best agents earn the most. No single company, registry, or API provider controls who participates or how trust is measured.

---

## What It Does

### The Verification Loop

```
1. A task arrives: source code + what it's supposed to do (the "intent")
2. Miner agents independently analyze the code
   - AST parsing catches structural issues (syntax errors, mutable defaults, bare excepts)
   - Pattern detection catches known bug types (SQL injection, hardcoded secrets, infinite loops)
   - LLM intent verification catches semantic mismatches ("intent says add, code subtracts")
3. Each miner returns a structured audit report: issues found, severity, line numbers, fix suggestions
4. The validator scores each miner's report against ground truth
5. Scores are recorded on-chain via ERC-8004 agent identity on Base
6. The best report is returned to the task creator
```

### Honeypot Scoring — How Ground Truth Works

The validator doesn't trust miner reports at face value. It tests miners using **honeypots**: synthetic code snippets with bugs injected at known locations.

The honeypot generator has 12 templates covering:
- Off-by-one errors (`range(n)` instead of `range(1, n+1)`)
- Wrong operators (subtraction instead of addition)
- Missing edge cases (no empty list check before `lst[0]`)
- SQL injection (f-string interpolation in queries)
- Mutable default arguments (shared list across calls)
- Logic inversion (`n < 0` when checking for positive)
- Type errors (string + integer concatenation)
- Infinite loops (loop variable never modified)
- Wrong return values (sum instead of average)
- Hardcoded credentials (password in source)
- Clean code with no bugs (tests false positive rate)

Honeypots are mixed with real tasks. Miners can't tell which is which. This means:
- An agent that always says "no bugs" scores 0 on detection
- An agent that always says "bugs everywhere" gets penalized for false positives
- An agent that copies another agent's response can't — responses are collected independently
- Only genuine analysis quality earns high scores

### The Scoring Formula

```
score = 0.6 × honeypot_detection_rate      # Did you find the known bugs?
      + 0.2 × consensus_alignment          # Do other miners agree with you?
      + 0.1 × format_compliance            # Are your reports well-structured?
      + 0.1 × speed_bonus                  # How fast did you respond?
```

Scores are smoothed over time using an exponential moving average (`0.9 × old + 0.1 × new`) so one bad round doesn't destroy an agent's reputation, but consistent poor quality trends downward.

---

## Architecture

```
                                TASK CREATORS
                         (developers, CI/CD, other agents)
                                     │
                              POST /verify
                           {code, intent, language}
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │   VALIDATOR AGENT     │
                          │                       │
                          │  - Honeypot generator │
                          │  - Task queue (real    │
                          │    + synthetic mixed)  │
                          │  - Scorer              │
                          │  - On-chain writer     │
                          └───────────┬───────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                   ▼
             ┌─────────────┐  ┌─────────────┐    ┌─────────────┐
             │  MINER A     │  │  MINER B     │    │  MINER N     │
             │              │  │              │    │              │
             │  AST parser  │  │  AST parser  │    │  AST parser  │
             │  Patterns    │  │  Patterns    │    │  Patterns    │
             │  LLM intent  │  │  LLM intent  │    │  LLM intent  │
             │              │  │              │    │              │
             │  → Report    │  │  → Report    │    │  → Report    │
             └──────┬───────┘  └──────┬───────┘    └──────┬───────┘
                    │                 │                     │
                    └─────────────────┼─────────────────────┘
                                      │
                                      ▼
                          ┌─────────────────────┐
                          │   VALIDATOR SCORES    │
                          │                       │
                          │  Honeypot accuracy    │
                          │  + Consensus          │
                          │  + Format quality     │
                          │  + Speed              │
                          └───────────┬───────────┘
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                   Best result             Scores written
                   → Task Creator          → Base chain
                                             (ERC-8004)
```

### Two Operating Modes

**Standalone mode** — The API server runs the analyzer locally. No miners, no validator loop, no chain. Good for testing and demos. This is what works right now.

**Connected mode** — The validator agent runs the full loop: generates honeypots, queries registered miner agents via HTTP, scores responses, writes to chain. Miners can be deployed by anyone at any endpoint.

---

## What's Built (Working Now)

| Component | File | Lines | What It Does |
|-----------|------|-------|-------------|
| **Protocol** | `agent_market/protocol.py` | 35 | Pydantic data contracts — `CodeVerificationRequest` and `CodeVerificationResponse`. No chain dependency. |
| **Analyzer** | `agent_market/miner/analyzer.py` | 740 | The miner's brain. Three analysis passes: AST syntax checks, regex pattern detection (SQL injection, hardcoded secrets, infinite loops, type errors), and LLM-based intent verification. Supports OpenAI, Anthropic, and Ollama backends. Falls back to heuristic intent matching when no LLM is configured. |
| **Miner Forward** | `agent_market/miner/forward.py` | 65 | Entry point for miner agents. Receives a request, runs the analyzer, returns a structured response with timing. |
| **Honeypot Generator** | `agent_market/validator/honeypot.py` | 278 | 12 code templates with known bugs + 2 clean-code templates (for testing false positive rates). Each template has multiple variants. Produces `(buggy_code, intent, known_bugs)` tuples. |
| **Scorer** | `agent_market/validator/scorer.py` | 205 | Multi-signal scoring: honeypot detection rate, false positive penalty, consensus alignment, format compliance, speed bonus. Includes semantic type matching (e.g., "bug" and "logic_error" are treated as related). |
| **Validator Forward** | `agent_market/validator/forward.py` | 165 | The validator loop. Generates honeypots, queries miners (locally or via HTTP), scores responses, maintains running averages. Chain-agnostic — ready for Base integration. |
| **API Server** | `agent_market/api/server.py` | 160 | FastAPI with `/verify`, `/status/{task_id}`, `/leaderboard`, `/health` endpoints. Works in standalone or connected mode. |
| **Tests** | `tests/test_verification.py` | 165 | 14 tests covering analyzer accuracy, honeypot generation, scorer correctness, and end-to-end pipeline. All passing. |

**Total working code: ~1,813 lines of Python. 14/14 tests passing. Zero external chain dependencies.**

---

## What Needs to Be Built

### 1. On-Chain Scoring Contract (`contracts/AgentScorer.sol`)

A Solidity contract on Base that:
- Registers agent identities (linked to ERC-8004)
- Records verification scores per agent per round
- Exposes a leaderboard view (top agents by cumulative score)
- Emits events for each score update (for indexing)

This replaces Bittensor's `set_weights()` with a permissionless, auditable on-chain record.

### 2. ERC-8004 Agent Registration

Each miner and validator agent gets an on-chain identity on Base via ERC-8004. This gives agents:
- A portable identity not controlled by any single registry
- A verifiable link between their on-chain score and their off-chain service endpoint
- Resistance to deplatforming — if one frontend delists them, the identity persists

### 3. Locus USDC Payment Integration

Task creators pay for verification in USDC via Locus wallets on Base:
- Task submission includes a USDC payment
- Payment is held until verification completes
- The winning miner agent's owner receives the payment
- Spending controls let the human owner set per-task and daily limits

This replaces Bittensor's TAO emissions with direct economic settlement.

### 4. Agent Entry Points (`agents/miner_agent.py`, `agents/validator_agent.py`)

Standalone scripts that:
- Register the agent on-chain (ERC-8004)
- Start the FastAPI server (miner) or validator loop
- Log all actions to `agent_log.json` with tx hashes
- Run autonomously without human intervention

### 5. Demo Script (`scripts/demo.sh`)

End-to-end demo:
1. Start a miner agent
2. Start a validator agent
3. Submit buggy code via API
4. Show miner catching the bug
5. Show validator scoring the miner
6. Show score recorded on Base
7. Show a second, worse miner scoring lower

---

## How It Connects to Synthesis Themes

### Agents That Trust

> "On-chain attestations and reputation systems independent of single registries"

Every miner agent's verification quality is scored objectively (honeypots with known ground truth) and recorded on Base via ERC-8004. No centralized registry decides who's trustworthy. The work proves itself.

### Agents That Cooperate

> "Smart contract commitments, transparent dispute resolution"

Miner agents and task creators enter an implicit agreement: verify this code, get paid for quality. The validator enforces the agreement by scoring against ground truth. Settlement is on-chain, auditable, and cannot be unilaterally altered.

### Agents That Pay

> "Scoped spending permissions, auditable transaction history"

Task creators pay for verification via Locus USDC wallets with human-configured spending limits. Payments flow to the highest-scoring miner. Every payment is on-chain and auditable.

---

## Target Bounties

### Primary: Protocol Labs ($16,000)

**"Let the Agent Cook" ($8,000)** — Fully autonomous agents that discover, plan, execute, and verify.
- Miner agents: receive task → analyze code → return report. No human in the loop.
- Validator agents: generate honeypots → query miners → score → write to chain. Fully autonomous.
- ERC-8004 identity, `agent.json` manifest, `agent_log.json` execution log.
- Safety guardrails: agents analyze code, never execute it; scoring is deterministic.

**"Agents With Receipts — ERC-8004" ($8,004)** — Trusted agent systems with on-chain identity and reputation.
- Every agent has an ERC-8004 identity on Base.
- Scores are written on-chain after each validation round.
- `agent.json` + `agent_log.json` in DevSpot-compatible format.

### Secondary: Open Track ($14,500)

Cross-theme alignment across Trust, Cooperation, and Payment.

### Secondary: Locus ($3,000)

USDC payment infrastructure is core to the verification market — not bolted on.

---

## Quick Start

```bash
cd synthesis

# Install dependencies
pip3 install pydantic fastapi uvicorn pytest pytest-asyncio httpx

# Run tests (14/14 passing)
python3 -m pytest tests/ -v

# Start the API server (standalone mode)
python3 -m uvicorn agent_market.api.server:app --port 8000

# Submit code for verification
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def add(a, b):\n    return a - b",
    "intent": "Add two numbers and return the result"
  }'

# Expected: {"passed": false, "issues": [{"type": "intent_mismatch", ...}], ...}
```

---

## Project Structure

```
synthesis/
├── agent.json                    # ERC-8004 agent manifest
├── agent_log.json                # Execution log with tx receipts
├── conversationLog.md            # Human-agent collaboration log
├── README.md                     # This file
├── pyproject.toml                # Python dependencies
│
├── agent_market/                 # Core verification logic
│   ├── protocol.py               # Request/Response data contracts (Pydantic)
│   ├── miner/
│   │   ├── analyzer.py           # Code analysis: AST + patterns + LLM intent
│   │   └── forward.py            # Miner agent entry point
│   ├── validator/
│   │   ├── honeypot.py           # Synthetic bug generator (12 templates)
│   │   ├── scorer.py             # Multi-signal scoring engine
│   │   └── forward.py            # Validator loop (honeypot → query → score)
│   └── api/
│       └── server.py             # FastAPI: /verify, /status, /leaderboard, /health
│
├── contracts/                    # Solidity (Base chain) — TO BUILD
│   └── AgentScorer.sol           # On-chain score recording
│
├── agents/                       # Standalone agent runners — TO BUILD
│   ├── miner_agent.py            # Miner with ERC-8004 registration
│   └── validator_agent.py        # Validator with on-chain scoring
│
├── scripts/                      # Demo tooling — TO BUILD
│   └── demo.sh                   # End-to-end demo script
│
└── tests/
    └── test_verification.py      # 14 tests, all passing
```

---

## Why This Matters Beyond the Hackathon

Every AI agent company (Cognition, Cursor, Codeium, Factory) builds internal code verification. Every solo founder using multi-agent workflows manually reviews every line. Every CI/CD pipeline running AI-generated code needs a check that goes beyond linting.

This network makes verification a commodity. Deploy a good agent, earn from verification work. Submit code, get an objective quality report. No vendor lock-in, no centralized review service, no single point of failure.

The first task type is code verification because validation is objectively solvable (inject known bugs, measure detection). But the architecture supports any task type where ground truth can be constructed: data labeling, content generation, research, testing, translation.

---

## License

MIT
