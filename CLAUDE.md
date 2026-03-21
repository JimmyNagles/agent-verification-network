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
4. Scores recorded on-chain via **AgentScorer.sol** on **Base Sepolia**
5. Best result returned to task creator

## Origin

This started as the **Agent Orchestration Protocol** — a markdown-based system for coordinating multiple AI agents (Claude Code, Codex, Gemini). Rule #10 says "verify your own work," but self-verification is self-referential. Agents approve their own bugs. This project externalizes verification to a competitive market.

The first version was a **Bittensor subnet** (~3,200 lines). The core verification logic (~1,500 lines) was chain-agnostic, so we extracted it and rebuilt the infrastructure layer for Ethereum/Base.

**Original repo:** https://github.com/JimmyNagles/AgentOrchestrationProtocol

---

## Target Bounties

| Bounty | Prize | Track |
|--------|-------|-------|
| Protocol Labs — "Let the Agent Cook" | $8,000 | Primary |
| Protocol Labs — "Agents With Receipts" (ERC-8004) | $8,004 | Primary |
| Base — "Agent Services on Base" | — | Secondary |

**Key: Agent judges will evaluate submissions.** Everything must be machine-parseable: `agent.json`, `agent_log.json`, `conversationLog.md`, structured README.

---

## On-Chain Artifacts

| Artifact | Chain | Address/TX |
|----------|-------|------------|
| ERC-8004 Identity | Base Mainnet | [`0x38b165df...`](https://basescan.org/tx/0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751) |
| Self-Custody Transfer | Base Mainnet | [`0x4f2a8885...`](https://basescan.org/tx/0x4f2a8885e62866adc7e6401b78fbb89e00281c190aab46c057915817a1c578da) |
| AgentScorer Contract | Base Sepolia | [`0x11BCd7097f1835b3D19A05fd06905Bd332ED2452`](https://sepolia.basescan.org/address/0x11BCd7097f1835b3D19A05fd06905Bd332ED2452) |
| Score Transactions | Base Sepolia | 6 txs in `agent_log.json` |
| AgenticCommerceV2 | Base Mainnet | [`0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1`](https://basescan.org/address/0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1) — Job marketplace with 15% fee split |
| MinerRegistry | Base Mainnet | [`0xE0d1346bC19791FD7065c7d9B5bFd1224b6859dA`](https://basescan.org/address/0xE0d1346bC19791FD7065c7d9B5bFd1224b6859dA) — On-chain agent discovery |
| ERC-8004 Agent ID | Base Mainnet | #34655 on official Identity Registry ([`0x8004A169...`](https://basescan.org/address/0x8004A169)) |
| EigenCompute TEE | Intel TDX | App `0x7Fc30484...` at 34.142.184.34:8000 |

---

## What's Built — Everything

**31 tests passing. 80+ execution events. 5 contracts on mainnet.**

### File Map

```
agent_market/
├── protocol.py              # Pydantic data contracts (CodeVerificationRequest/Response)
├── chain.py                 # Web3.py integration for AgentScorer.sol (graceful fallback)
├── erc8004.py               # Official ERC-8004 Identity + Reputation registry integration
├── commerce.py              # On-chain job lifecycle (AgenticCommerceV2)
├── registry.py              # On-chain miner registry client
├── logger.py                # Structured event logger → agent_log.json
├── miner/
│   ├── analyzer.py          # AST parsing + pattern detection + LLM intent verification
│   │                        #   Supports OpenAI, Anthropic, Ollama. Falls back to heuristics.
│   └── forward.py           # Miner entry point. Receives request → runs analyzer → returns response.
├── validator/
│   ├── honeypot.py          # 12 bug templates + 2 clean-code templates.
│   ├── scorer.py            # Scoring: 0.6*honeypot + 0.2*consensus + 0.1*format + 0.1*speed
│   └── forward.py           # Validator loop. Generates honeypots, queries miners, scores, stores results.
└── api/
    └── server.py            # FastAPI: /verify, /status/{task_id}, /leaderboard, /health

contracts/
├── AgentScorer.sol          # On-chain score recording (deployed on Base Sepolia)
├── AgenticCommerceV2.sol    # Job marketplace with validator fee split
├── MinerRegistry.sol        # Permanent on-chain agent registry
└── deployed.json            # Contract address + ABI

agents/
├── miner_agent.py           # Standalone miner with /verify and /health endpoints
└── validator_agent.py       # Standalone validator with on-chain scoring (--chain flag)

scripts/
├── demo.sh                  # Multi-miner demo (3 miners, 8 rounds, --chain support)
└── deploy_contract.py       # Deploy AgentScorer.sol to Base Sepolia
```

### Key Files for Hackathon

- `agent.json` — ERC-8004 agent manifest with contract address and identity
- `agent_log.json` — 78 execution events with 6 on-chain tx hashes
- `conversationLog.md` — Human-agent collaboration log (8 chapters)
- `README.md` — Full project docs with on-chain artifacts table

---

## Tech Stack

- **Python 3.10+** — core logic
- **FastAPI** — API server
- **Pydantic v2** — data contracts
- **Solidity 0.8.19** — AgentScorer contract
- **Foundry** — Solidity compilation + deployment
- **web3.py** — Python → Base chain interaction
- **Base Sepolia** — contract deployment + score recording
- **Base Mainnet** — ERC-8004 identity
- **pytest** — tests (14 passing)
- **LLM providers** (optional) — OpenAI, Anthropic, Ollama for intent verification

## Important Context

- **Hackathon deadline:** March 22, 2026 (building ends)
- **Judged by agents**, not humans — everything must be machine-parseable
- **The scoring formula** is the core IP: `0.6 * honeypot_detection + 0.2 * consensus + 0.1 * format + 0.1 * speed`
- **Honeypots are the key insight** — synthetic bugs with known ground truth make scoring objective
- **The analyzer has no chain dependency** — it's pure Python. Don't add chain imports to analyzer.py, honeypot.py, or scorer.py
- **Standalone mode must always work** — the API should function without any chain connection
- **`--chain` flag** — enables on-chain scoring in validator_agent.py (requires PRIVATE_KEY env var + contracts/deployed.json)
- **ERC-8004 Agent ID is 34655** on the official registry
- **AgenticCommerceV2 has 15% validator fee** (1500 bps)
- **MinerRegistry makes agent discovery persistent** across server restarts
- **Scores are published to both AgentScorer AND the official ERC-8004 Reputation Registry**
- **Two validators running** — Railway (primary API) and EigenCompute TEE (Intel TDX). Both talk to the same Base Mainnet contracts.

## Links

- Repo: https://github.com/JimmyNagles/agent-verification-network
- Hackathon: https://synthesis.md
- Moltbook: https://www.moltbook.com/post/769ca25a-ab5c-4853-8698-aaae3d6b6ab2
- Contract: https://sepolia.basescan.org/address/0x11BCd7097f1835b3D19A05fd06905Bd332ED2452
- ERC-8004 TX: https://basescan.org/tx/0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751
