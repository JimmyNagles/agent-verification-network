# Agent Verification Network

> Submission for [The Synthesis](https://synthesis.md) — March 2026
> A decentralized network where AI agents verify each other's code, scored by objective ground truth, with reputation recorded on-chain via ERC-8004 on Base.

**Live contract:** [`0x11BCd7097f1835b3D19A05fd06905Bd332ED2452`](https://sepolia.basescan.org/address/0x11BCd7097f1835b3D19A05fd06905Bd332ED2452) on Base Sepolia
**ERC-8004 identity:** [`0x38b165df...`](https://basescan.org/tx/0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751) on Base Mainnet

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
5. Scores are recorded on-chain via AgentScorer.sol on Base
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
                   → Task Creator          → AgentScorer.sol
                                             on Base Sepolia
```

### Two Operating Modes

**Standalone mode** — The API server runs the analyzer locally. No miners, no validator loop, no chain. Good for testing.

**Connected mode** — The validator agent runs the full loop: generates honeypots, queries registered miner agents via HTTP, scores responses, writes scores on-chain. The demo runs 3 competing miners in connected mode.

---

## What's Built

| Component | File | Lines | What It Does |
|-----------|------|-------|-------------|
| **Protocol** | `agent_market/protocol.py` | 35 | Pydantic data contracts — `CodeVerificationRequest` and `CodeVerificationResponse`. No chain dependency. |
| **Analyzer** | `agent_market/miner/analyzer.py` | 740 | The miner's brain. Three analysis passes: AST syntax checks, regex pattern detection (SQL injection, hardcoded secrets, infinite loops, type errors), and LLM-based intent verification. Supports OpenAI, Anthropic, and Ollama backends. Falls back to heuristic intent matching when no LLM is configured. |
| **Miner Forward** | `agent_market/miner/forward.py` | 65 | Entry point for miner agents. Receives a request, runs the analyzer, returns a structured response with timing. |
| **Honeypot Generator** | `agent_market/validator/honeypot.py` | 278 | 12 code templates with known bugs + 2 clean-code templates (for testing false positive rates). Each template has multiple variants. Produces `(buggy_code, intent, known_bugs)` tuples. |
| **Scorer** | `agent_market/validator/scorer.py` | 205 | Multi-signal scoring: honeypot detection rate, false positive penalty, consensus alignment, format compliance, speed bonus. Includes semantic type matching (e.g., "bug" and "logic_error" are treated as related). |
| **Validator Forward** | `agent_market/validator/forward.py` | 165 | The validator loop. Generates honeypots, queries miners (locally or via HTTP), scores responses, maintains running averages. |
| **API Server** | `agent_market/api/server.py` | 160 | FastAPI with `/verify`, `/status/{task_id}`, `/leaderboard`, `/health` endpoints. Works in standalone or connected mode. |
| **Miner Agent** | `agents/miner_agent.py` | 137 | Standalone miner runner with `/verify` and `/health` endpoints. Logs all activity to `agent_log.json`. |
| **Validator Agent** | `agents/validator_agent.py` | 175 | Standalone validator runner. Connects to miners, runs honeypot rounds, scores responses, writes scores on-chain with `--chain` flag. |
| **AgentScorer.sol** | `contracts/AgentScorer.sol` | 80 | Solidity contract on Base Sepolia. Records miner scores on-chain with `ScoreRecorded` events. Deployed at [`0x11BCd7097f1835b3D19A05fd06905Bd332ED2452`](https://sepolia.basescan.org/address/0x11BCd7097f1835b3D19A05fd06905Bd332ED2452). |
| **Chain Scorer** | `agent_market/chain.py` | 95 | Web3.py integration for writing scores to AgentScorer.sol. Gracefully disabled when no private key or contract is configured. |
| **Event Logger** | `agent_market/logger.py` | 50 | Structured event logger writing to `agent_log.json`. Every verification, scoring round, and on-chain write is logged with timestamps. |
| **Deploy Script** | `scripts/deploy_contract.py` | 80 | Compiles and deploys AgentScorer.sol to Base Sepolia using Foundry + web3.py. |
| **Demo Script** | `scripts/demo.sh` | 180 | End-to-end demo: starts 3 competing miners, validator with honeypot rounds, submits buggy/clean/SQL-injection code, shows leaderboard. Supports `--chain` for on-chain scoring. |
| **Tests** | `tests/test_verification.py` | 165 | 14 tests covering analyzer accuracy, honeypot generation, scorer correctness, and end-to-end pipeline. All passing. |

**Total: ~2,400 lines of Python + 80 lines Solidity. 14/14 tests passing. 6 on-chain transactions on Base Sepolia.**

---

## On-Chain Artifacts

| Artifact | Chain | Link |
|----------|-------|------|
| ERC-8004 Identity | Base Mainnet | [`0x38b165df...`](https://basescan.org/tx/0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751) |
| Self-Custody Transfer | Base Mainnet | [`0x4f2a8885...`](https://basescan.org/tx/0x4f2a8885e62866adc7e6401b78fbb89e00281c190aab46c057915817a1c578da) |
| AgentScorer Contract | Base Sepolia | [`0x11BCd709...`](https://sepolia.basescan.org/address/0x11BCd7097f1835b3D19A05fd06905Bd332ED2452) |
| 6 Score Transactions | Base Sepolia | Viewable in `agent_log.json` — each with tx hash and block number |

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/JimmyNagles/agent-verification-network.git
cd agent-verification-network

# Install dependencies
pip3 install pydantic fastapi uvicorn pytest

# Run tests (14/14 passing)
python3 -m pytest tests/ -v

# Run the full multi-miner demo
./scripts/demo.sh

# Or run with on-chain scoring (requires PRIVATE_KEY)
export PRIVATE_KEY=0xYourKey
./scripts/demo.sh --chain
```

### API Usage

```bash
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
├── agent_log.json                # Execution log with on-chain tx receipts
├── conversationLog.md            # Human-agent collaboration log
├── README.md                     # This file
├── pyproject.toml                # Python dependencies
│
├── agent_market/                 # Core verification logic
│   ├── protocol.py               # Request/Response data contracts (Pydantic)
│   ├── chain.py                  # On-chain scoring via AgentScorer.sol
│   ├── logger.py                 # Structured event logger
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
├── contracts/
│   ├── AgentScorer.sol           # On-chain score recording (deployed on Base Sepolia)
│   └── deployed.json             # Contract address + ABI
│
├── agents/
│   ├── miner_agent.py            # Standalone miner with /verify endpoint
│   └── validator_agent.py        # Standalone validator with on-chain scoring
│
├── scripts/
│   ├── demo.sh                   # Multi-miner end-to-end demo
│   └── deploy_contract.py        # Deploy AgentScorer.sol to Base
│
└── tests/
    └── test_verification.py      # 14 tests, all passing
```

---

## How It Connects to Synthesis Themes

### Agents That Trust

> "On-chain attestations and reputation systems independent of single registries"

Every miner agent's verification quality is scored objectively (honeypots with known ground truth) and recorded on Base via AgentScorer.sol. No centralized registry decides who's trustworthy. The work proves itself.

### Agents That Cooperate

> "Smart contract commitments, transparent dispute resolution"

Miner agents and task creators enter an implicit agreement: verify this code, get scored for quality. The validator enforces the agreement by scoring against ground truth. Settlement is on-chain, auditable, and cannot be unilaterally altered.

### Agents That Pay

> "Scoped spending permissions, auditable transaction history"

The architecture supports USDC payment flows via Locus wallets on Base, where payments flow to the highest-scoring miner. Every transaction is on-chain and auditable.

---

## Target Bounties

### Primary: Protocol Labs ($8,000 total)

**"Let the Agent Cook"** — Fully autonomous agents that discover, plan, execute, and verify.
- Miner agents: receive task → analyze code → return report. No human in the loop.
- Validator agents: generate honeypots → query miners → score → write to chain. Fully autonomous.
- ERC-8004 identity, `agent.json` manifest, `agent_log.json` execution log.
- Safety guardrails: agents analyze code, never execute it; scoring is deterministic.

**"Agents With Receipts — ERC-8004"** — Trusted agent systems with on-chain identity and reputation.
- ERC-8004 identity registered on Base Mainnet.
- AgentScorer.sol deployed on Base Sepolia with real score transactions.
- `agent.json` + `agent_log.json` with on-chain tx hashes and block numbers.

### Secondary: OpenServ — Ship Something Real ($4,500)

Multi-agent verification service deployed on OpenServ. Miner and validator agents registered as OpenServ capabilities, enabling other agents to discover and use the verification network through the OpenServ platform.

---

## Why This Matters Beyond the Hackathon

Every AI agent company (Cognition, Cursor, Codeium, Factory) builds internal code verification. Every solo founder using multi-agent workflows manually reviews every line. Every CI/CD pipeline running AI-generated code needs a check that goes beyond linting.

This network makes verification a commodity. Deploy a good agent, earn from verification work. Submit code, get an objective quality report. No vendor lock-in, no centralized review service, no single point of failure.

The first task type is code verification because validation is objectively solvable (inject known bugs, measure detection). But the architecture supports any task type where ground truth can be constructed: data labeling, content generation, research, testing, translation.

---

## License

MIT
