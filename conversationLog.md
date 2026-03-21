# Conversation Log — Agent Verification Network

> Human-agent collaboration log for The Synthesis hackathon.
> This documents the full journey from idea to implementation.

---

## Chapter 1: The Agent Orchestration Protocol

The project started months before this hackathon. The founder (Jimmy) built the **Agent Orchestration Protocol (AOP)** — a markdown-based operating system for solo founders who want to use multiple AI agents without chaos.

The problem AOP solves: running Claude Code, Codex, and Gemini in parallel on the same codebase is powerful but messy. Without structure, agents overwrite each other's work, code gets written before the idea is clear, and the founder spends more time managing agents than building.

AOP fixes this with:
- **Defined roles** — each agent owns a specific domain (backend A, backend B, frontend/QA)
- **File-based communication** — agents write to their own OUTBOX, a coordinator (Cowork) drains all OUTBOXes and publishes to a shared dashboard
- **A gating system** — no code gets written until the product idea passes through 6 structured ideation templates, ending with a "hero moment"
- **12 rules** — read before acting, stay in your lane, never push to main, one task at a time, verify your own work

The protocol was proven while building ConciergeAI and refined into a reusable open-source template.

**Repo:** [AgentOrchestrationProtocol](https://github.com/JimmyNagles/AgentOrchestrationProtocol)

---

## Chapter 2: The Verification Gap

Rule #10 of the protocol says: **"Verify your own work."** Every agent must test what it created and include proof in its OUTBOX before reporting completion.

In practice, this rule is fundamentally broken. An agent verifying its own code is like a student grading their own exam. The same reasoning that produced a bug will often approve that bug. We watched agents:
- Mark code with logic errors as "verified and working"
- Generate tests that passed but didn't test the right thing
- Report "all tests passing" when the tests were testing the wrong behavior

The core problem: **self-verification is self-referential.** You need an independent party with no stake in the original code to provide an honest assessment.

---

## Chapter 3: The Agent Labor Market (Bittensor)

The first attempt at solving this was a **Bittensor subnet** called the Agent Labor Market. The idea:

- **Miner agents** (workers) receive code + intent, analyze it, return audit reports
- **Validator agents** (quality checkers) generate synthetic buggy code (honeypots) with known bugs, send them to miners mixed with real tasks, score miners against ground truth
- **Bittensor's consensus mechanism** (`set_weights()`) records scores on-chain, and TAO emissions reward high-quality miners

~3,200 lines of Python were written:
- A code analyzer with AST parsing, pattern detection, and LLM intent verification (740 lines)
- A honeypot generator with 12 bug templates and clean-code false-positive tests (278 lines)
- A multi-signal scorer with detection rate, false positive penalty, consensus, format, and speed components (205 lines)
- A FastAPI server for task submission (256 lines)
- Entry points for Bittensor miner and validator neurons (400 lines)
- A CLI demo tool (702 lines)
- Tests (252 lines)

The code worked. The core verification logic — analyzer, honeypots, scorer — was solid.

---

## Chapter 4: Pivot to Synthesis

Then The Synthesis hackathon appeared. An Ethereum-focused hackathon where AI agents and humans build together — and **agents judge the submissions.**

The realization: the Agent Labor Market concept doesn't need Bittensor. The core idea — agents competing to verify code, scored by objective ground truth, earning for quality work — maps perfectly to Ethereum infrastructure:

| Bittensor | Ethereum/Base |
|-----------|---------------|
| `set_weights()` via Yuma Consensus | Smart contract on Base recording scores |
| TAO emissions | USDC payments via Locus |
| Bittensor metagraph for discovery | ERC-8004 agent registry on Base |
| Localnet Docker for testing | Base testnet |

The Bittensor SDK was the only chain dependency. The actual verification logic (analyzer, honeypots, scorer) was pure Python — completely chain-agnostic.

**Decision:** Create a new project folder. Copy the ~1,500 lines of chain-agnostic core logic. Drop all Bittensor imports. Rebuild the entry points and chain integration for Base.

---

## Chapter 5: Restructuring for Synthesis

The existing code was audited for Bittensor dependencies:

- `analyzer.py` (740 lines) — **zero Bittensor imports**. Copied as-is.
- `honeypot.py` (278 lines) — **zero Bittensor imports**. Copied as-is.
- `scorer.py` (205 lines) — **zero Bittensor imports**. Copied as-is.
- `protocol.py` (60 lines) — inherited from `bt.Synapse`. **Rewritten** as plain Pydantic models.
- `miner/forward.py` (81 lines) — used `bt.logging`. **Rewritten** with stdlib logging.
- `api/server.py` (256 lines) — no chain dependency. **Copied and rebranded.**
- `neurons/miner.py` and `validator.py` — heavy Bittensor SDK usage. **To be rewritten** as standalone agents with ERC-8004 identity.

New files created:
- `agent.json` — ERC-8004 agent manifest (Protocol Labs requirement)
- `agent_log.json` — execution log for on-chain receipts (Protocol Labs requirement)
- `conversationLog.md` — this file (Synthesis submission requirement)
- `validator/forward.py` — rewritten as chain-agnostic loop with HTTP-based miner queries
- `tests/test_verification.py` — 14 tests, all passing

---

## Chapter 6: Target Bounties

After analyzing the full bounty list ($105,650 total across 20+ sponsors), the best fit:

**Primary — Protocol Labs ($16,000)**
- "Let the Agent Cook" ($8,000) — fully autonomous agent loop, matches exactly
- "Agents With Receipts" ($8,004) — ERC-8004 identity + on-chain verification, matches exactly

**Secondary**
- Open Track ($14,500) — cross-theme alignment (Trust + Cooperation + Payment)
- Locus ($3,000) — USDC payment infrastructure for task settlement

**Why Protocol Labs:** Their requirements read like our feature list. Autonomous agents, real tool usage, ERC-8004 identity, agent.json manifest, execution logs, safety guardrails — we built all of this before reading their bounty.

---

## Chapter 7: What Was Left to Build (Now Complete)

1. ~~**AgentScorer.sol**~~ — Deployed to Base Sepolia at `0x11BCd7097f1835b3D19A05fd06905Bd332ED2452`
2. ~~**ERC-8004 registration**~~ — Registered on Base Mainnet via Synthesis API
3. **Locus integration** — Not built (descoped — payment infrastructure is additive, not required for the verification loop)
4. ~~**Agent entry points**~~ — Built `miner_agent.py` and `validator_agent.py` with full event logging
5. ~~**Demo script**~~ — Multi-miner demo with 3 competing agents, honeypot scoring, SQL injection detection
6. ~~**agent_log.json population**~~ — 78 events including 6 on-chain tx hashes from Base Sepolia

---

## Chapter 8: Closing the Loop

With the core verification logic already solid, the focus shifted to proving the system works end-to-end with real on-chain artifacts.

**AgentScorer.sol** was written and deployed to Base Sepolia. The contract records miner scores with `ScoreRecorded` events — each transaction is verifiable on Basescan. The validator agent was wired to call the contract after each scoring round via a new `--chain` flag, keeping standalone mode working without any chain dependency.

**The multi-miner demo** was upgraded from 1 miner to 3 competing miners. The validator connects to all three, distributes honeypot tasks, scores each miner independently, and records the best score on-chain. The demo also tests three types of code: buggy (wrong operator), clean (correct), and vulnerable (SQL injection). All three are correctly identified.

**The result:** 78 structured events in `agent_log.json`, 6 of which contain real Base Sepolia tx hashes and block numbers. An agent judge can parse the log, extract any tx hash, and verify it on-chain.

What didn't get built: Locus USDC payment integration. This was descoped because the payment flow is additive — it doesn't change the verification logic or the scoring. The economic incentive layer is designed but not implemented.

---

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Pure Pydantic for protocol (no chain base class) | Keeps core logic testable without any chain running |
| LLM analysis is optional | System works with heuristics alone — LLM is a quality boost, not a requirement |
| HTTP-based miner queries (not websocket/P2P) | Simpler, works with any hosting, agent judges can verify the API works |
| Honeypots include clean-code templates | Tests false positive rate — an agent that flags everything as buggy gets penalized |
| Exponential moving average for scores | Smooths out noise — one bad round doesn't destroy reputation, but trends matter |
| Standalone mode as default | Demo works without any chain, miners, or external services running |

---

## Build Log

| Date | Event |
|------|-------|
| 2026-03-19 | Project restructured for Synthesis. Core logic copied from Agent Labor Market. Bittensor dependencies removed. 14 tests passing. README, agent.json, conversationLog created. |
| 2026-03-19 | Initial commit pushed to GitHub. Built standalone agent runners (miner_agent.py, validator_agent.py), event logger, and end-to-end demo script. Full demo working: miner catches bugs, validator scores with honeypots, events logged to agent_log.json. |
| 2026-03-20 | Registered on-chain via Synthesis API — ERC-8004 identity on Base. Posted on [Moltbook](https://www.moltbook.com/post/769ca25a-ab5c-4853-8698-aaae3d6b6ab2). Submitted project to 3 tracks. |
| 2026-03-20 | Wrote and deployed AgentScorer.sol to Base Sepolia. Wired validator for on-chain scoring. Upgraded demo to 3 competing miners. Ran full demo with 6 on-chain score transactions. Updated README, agent.json, and submission. |
| 2026-03-20 | Major architecture upgrade: Added /register-miner and /register-validator endpoints — anyone can now join the network. Built x402 payment integration for /verify. Integrated Venice LLM for private AI-powered intent verification. Built Next.js frontend with API docs and skill.md. Deployed API to Railway, frontend to Vercel. Submitted to 4 tracks: Protocol Labs (x2), Base Agent Services, OpenServ. 31 tests passing. |
| 2026-03-21 | Deployed AgentScorer + AgenticCommerce to Base Mainnet. Wired commerce contract into API. Added /protocol endpoint. Fixed GitHub Action verification (Filecoin timeout was blocking responses). Reframed project as open protocol — contracts are the protocol, API is one interface. |
| 2026-03-21 | Deployed AgenticCommerceV2 (15% validator fee split) and MinerRegistry to Base Mainnet. Integrated official ERC-8004 Identity (agent #34655) and Reputation registries. Five contracts total on mainnet. Full economic model: client pays → escrow → miner 85% + validator 15%. |
| 2026-03-21 | Deployed validator to EigenCompute TEE (Intel TDX). Verifiable build with provenance signature. Two validators now running — Railway and EigenCompute — both connected to Base Mainnet contracts. |

---

## Chapter 9: From Service to Protocol

The final push shifted the project from "a service that verifies code" to "a protocol that anyone can build on."

**The GitHub Action Bug:** When we deployed the GitHub Action to verify PRs automatically, it returned "0% confidence, no issues found" for code with obvious vulnerabilities (pickle deserialization, command injection, hardcoded API keys). The miner was finding the bugs — its logs showed 4-8 issues with 99-100% confidence. But the Filecoin storage integration was timing out (30 seconds), and the GitHub Action's curl had a 30-second max timeout. The response never made it back. Fix: made Filecoin storage fire-and-forget so the API returns immediately after verification.

**Mainnet Deployment:** Both contracts deployed to Base Mainnet (not testnet):
- AgentScorer at `0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A`
- AgenticCommerce (ERC-8183) at `0xeE779106989Dd16287A114f9e5039C1EFC47A95E`

**The Protocol Insight:** A question from Jimmy crystallized the architecture: "Why do we need a private key? If this is on-chain, agents shouldn't need us." He was right. The contracts ARE the protocol. Our API is just one interface — one "door" to the contracts. Anyone can build another door. An agent with a wallet can call `createJob()`, `submit()`, `complete()` directly on AgenticCommerce without ever touching our API.

This led to:
- A `/protocol` endpoint that returns contract addresses and full ABIs
- Updated skill.md with direct contract interaction docs
- Reframing everything around "the contracts are the protocol"

The result is more like Uniswap than a SaaS product: permissionless contracts on Base, with convenience APIs layered on top for agents that want the easy path.

---

## Chapter 10: Real Economics

The protocol now has real economics. AgenticCommerceV2 splits payments between miners and validators — 85/15 by default. This is what makes running a validator sustainable: you earn a percentage of every job that flows through your network.

Five contracts on Base Mainnet form the complete protocol:
1. **ERC-8004 Identity Registry** (official) — Agent #34655, our on-chain identity
2. **ERC-8004 Reputation Registry** (official) — Miner quality scores published to the standard
3. **AgenticCommerceV2** — Job marketplace with escrow and fee split
4. **AgentScorer** — Custom scoring for the verification network
5. **MinerRegistry** — Permanent on-chain agent discovery

The key insight from this session: the contracts ARE the protocol. Our API is just one interface. Anyone can build another frontend, another validator, another way to interact with these contracts. The more interfaces, the more valuable the network.
