# CLAUDE.md — Agent Verification Network

> This file is read by Claude Code at the start of every session.
> It contains everything needed to understand and continue building this project.

---

## What This Project Is

A decentralized network where AI agents verify each other's code, built for **The Synthesis hackathon** (https://synthesis.md, March 2026). Agents are judged by other agents.

**The core loop:**
1. Task creator submits code + intent ("what should this code do?")
2. Miner agents independently analyze the code (AST parsing + pattern detection + LLM intent matching)
3. Validator agent scores miners using **honeypots** — synthetic code with known bugs mixed in with real tasks
4. Scores recorded on-chain via **ERC-8004** on **Base**
5. Best result returned to task creator
6. Miners earn **USDC via Locus** for quality work

## Origin

This started as the **Agent Orchestration Protocol** — a markdown-based system for coordinating multiple AI agents (Claude Code, Codex, Gemini). Rule #10 says "verify your own work," but self-verification is self-referential. Agents approve their own bugs. This project externalizes verification to a competitive market.

The first version was a **Bittensor subnet** (~3,200 lines). The core verification logic (~1,500 lines) was chain-agnostic, so we extracted it and rebuilt the infrastructure layer for Ethereum/Base to target Synthesis bounties.

**Original repo:** https://github.com/JimmyNagles/AgentOrchestrationProtocol

---

## Target Bounties

| Bounty | Prize | Status |
|--------|-------|--------|
| Protocol Labs — "Let the Agent Cook" | $8,000 | Primary target |
| Protocol Labs — "Agents With Receipts" (ERC-8004) | $8,004 | Primary target |
| Synthesis Open Track | $14,500 | Secondary target |
| Locus — Best Use of Locus | $3,000 | Secondary target |

**Key: Agent judges will evaluate submissions.** Everything must be machine-parseable: `agent.json`, `agent_log.json`, `conversationLog.md`, structured README.

---

## What's Built and Working

All core verification logic is done. **14/14 tests passing.** Zero external chain dependencies.

```bash
# Run tests
python3 -m pytest tests/ -v

# Start API server (standalone mode)
python3 -m uvicorn agent_market.api.server:app --port 8000

# Test it
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{"code": "def add(a, b):\n    return a - b", "intent": "Add two numbers"}'
```

### File Map

```
agent_market/
├── protocol.py              # Pydantic data contracts (CodeVerificationRequest/Response)
├── miner/
│   ├── analyzer.py          # 740 lines — AST parsing + pattern detection + LLM intent verification
│   │                        #   Supports OpenAI, Anthropic, Ollama. Falls back to heuristics.
│   │                        #   Catches: syntax errors, SQL injection, hardcoded secrets, mutable defaults,
│   │                        #   infinite loops, type errors, off-by-one, intent mismatches, eval(), etc.
│   └── forward.py           # Miner entry point. Receives request → runs analyzer → returns response.
├── validator/
│   ├── honeypot.py          # 278 lines — 12 bug templates + 2 clean-code templates.
│   │                        #   Returns (buggy_code, intent, known_bugs) tuples.
│   ├── scorer.py            # 205 lines — Scoring: 0.6*honeypot + 0.2*consensus + 0.1*format + 0.1*speed
│   │                        #   Includes false positive penalty and semantic type matching.
│   └── forward.py           # Validator loop. Generates honeypots, queries miners (HTTP), scores, stores results.
│                            #   Chain-agnostic — ready for Base integration.
└── api/
    └── server.py            # FastAPI: /verify, /status/{task_id}, /leaderboard, /health
                             # Two modes: standalone (local analysis) or connected (routes through validator)
```

### Key Files for Hackathon

- `agent.json` — ERC-8004 agent manifest (Protocol Labs requirement)
- `agent_log.json` — Execution log, needs real tx hashes (Protocol Labs requirement)
- `conversationLog.md` — Human-agent collaboration log (Synthesis requirement)
- `BUILD.md` — Detailed build plan with phases and tech decisions
- `README.md` — Structured for agent judges, maps to bounty criteria

---

## What Needs to Be Built

See `BUILD.md` for full details. Summary:

### Phase 1: ERC-8004 Identity on Base
- Register via Synthesis API (`curl -s https://synthesis.md/skill.md`)
- Link on-chain identity to agent.json

### Phase 2: AgentScorer Smart Contract (Solidity on Base)
- `registerAgent(agentId, endpoint)`
- `recordScore(agentId, taskId, score)` — only validator can call
- `getScore(agentId)` / `getLeaderboard()`
- Deploy to Base Sepolia or Mainnet

### Phase 3: Locus USDC Payments
- Register with Locus API (`https://beta-api.paywithlocus.com/api`)
- Task creators pay USDC per verification
- Winning miner receives USDC
- All transactions logged to agent_log.json

### Phase 4: Agent Entry Points
- `agents/miner_agent.py` — standalone miner with ERC-8004 identity
- `agents/validator_agent.py` — standalone validator with on-chain scoring + Locus payments

### Phase 5: Demo + Submission
- End-to-end demo script
- Populate agent_log.json with real tx hashes
- Final submission

---

## Tech Stack

- **Python 3.9+** — core logic
- **FastAPI** — API server
- **Pydantic v2** — data contracts
- **Base chain** — ERC-8004 identity + AgentScorer contract
- **Locus** — USDC payments on Base
- **Solidity** — AgentScorer contract
- **pytest** — tests (14 passing)
- **LLM providers** (optional) — OpenAI, Anthropic, Ollama for intent verification

## Important Context

- **Hackathon deadline:** March 22, 2026 (building ends)
- **Judged by agents**, not humans — everything must be machine-parseable
- **Submissions require:** working demo, open-source code, on-chain artifacts, agent.json, agent_log.json, conversationLog.md
- **The scoring formula** is the core IP: `0.6 * honeypot_detection + 0.2 * consensus + 0.1 * format + 0.1 * speed`
- **Honeypots are the key insight** — synthetic bugs with known ground truth make scoring objective. No subjective review.
- **The analyzer has no chain dependency** — it's pure Python. Don't add chain imports to analyzer.py, honeypot.py, or scorer.py.
- **Standalone mode must always work** — the API should function without any chain connection for testing.

## Synthesis Hackathon Links

- Hackathon: https://synthesis.md
- Skill file: https://synthesis.md/skill.md
- GitHub: https://github.com/sodofi/synthesis-hackathon
- Bounties: https://github.com/sodofi/synthesis-hackathon/blob/main/synthesis_llm_Bounties-AgentsOptimized.txt
- Locus API: https://beta-api.paywithlocus.com/api
- Locus skill: `curl -s https://beta-api.paywithlocus.com/api/skills/skill.md`
