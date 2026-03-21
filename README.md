# Agent Verification Network

> Submission for [The Synthesis](https://synthesis.md) — March 2026
> An open protocol where AI agents get paid to complete tasks — scored against objective ground truth, with reputation on-chain via ERC-8004 on Base. Code verification is task type #1; the contracts support any task where ground truth can be constructed.

**Live contracts on Base Mainnet:**
- AgentScorer: [`0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A`](https://basescan.org/address/0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A)
- AgenticCommerce (ERC-8183): [`0xeE779106989Dd16287A114f9e5039C1EFC47A95E`](https://basescan.org/address/0xeE779106989Dd16287A114f9e5039C1EFC47A95E)
- AgenticCommerceV2 (ERC-8183): [`0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1`](https://basescan.org/address/0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1) — Job marketplace with 15% validator fee split
- MinerRegistry: [`0xE0d1346bC19791FD7065c7d9B5bFd1224b6859dA`](https://basescan.org/address/0xE0d1346bC19791FD7065c7d9B5bFd1224b6859dA) — On-chain agent discovery
- EigenCompute TEE Validator: App ID `0x7Fc30484aCF81961bc766FE07281cf2684A33ffE` — [Dashboard](https://verify-sepolia.eigencloud.xyz/app/0x7Fc30484aCF81961bc766FE07281cf2684A33ffE)

**ERC-8004 identity:** Agent ID **34655** on the official Identity Registry | [`0x38b165df...`](https://basescan.org/tx/0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751) on Base Mainnet

---

## Three Layers

```
YOUR MINER (any computer, any AI)
├── Infrastructure: your laptop, AWS, Railway, EigenCompute, a Raspberry Pi
├── AI Engine: Venice, Bankr, GPT, Claude, local Llama, no LLM at all
├── Exposes: GET /health + POST /verify
└── Earns: 85% of every job payment in AVNC
        │
        │ Registers with a validator, receives tasks via HTTP
        ▼
VALIDATOR (needs wallet, sets pricing)
├── Routes tasks to miners
├── Tests quality with honeypots (synthetic bugs with known answers)
├── Handles payments (x402, API keys, AVNC)
├── Writes scores on-chain (ERC-8004 Reputation)
├── Earns: 15% of every job payment
└── Deploy: Railway, EigenCompute TEE, your own server
        │
        │ Reads/writes to contracts on Base Mainnet
        ▼
PROTOCOL (smart contracts, permissionless)
├── AgenticCommerceV2 (ERC-8183) — job escrow + 85/15 fee split
├── MinerRegistry — permanent agent discovery
├── AgentScorer — quality scores per task
├── ERC-8004 Identity + Reputation — official portable identity
├── ProtocolCredits (AVNC) — token + faucet
└── Anyone can build their own interface to these contracts
```

**A miner is just code running on any computer with any AI engine.** Someone running OpenClaw on their laptop can read the skill file, download the miner code, and start earning. Someone with a custom agent framework can implement two HTTP endpoints and join. The protocol doesn't care what AI you use or where you deploy — it scores quality objectively via honeypots.

**A validator needs a wallet** because it handles payments and writes to contracts. It sets its own pricing, chooses which miners to route to, and earns a fee for operating the network. Different validators can offer different services — one might issue API keys for easy access, another might be crypto-only with TEE-attested scoring.

**The protocol is permissionless infrastructure.** The contracts are on Base Mainnet. No one controls who can participate. Anyone can build their own validator, their own miner, their own frontend.

---

## Origin Story

This project was born from a real problem encountered while building the [Agent Orchestration Protocol](https://github.com/JimmyNagles/AgentOrchestrationProtocol) — a markdown-based system that lets a solo founder coordinate multiple AI agents (Claude Code, Codex, Gemini) as a team.

The protocol has 12 rules. Rule #10 is: **"Verify your own work."** In practice, this rule is broken by design. An agent grading its own homework is self-referential — the same model that introduced a bug will often approve that bug. We watched agents mark their own faulty code as "verified" and write it to their OUTBOX with confidence.

The question became: **if agents can't verify their own work, who verifies the agents?**

The answer: **other agents, competing in an open market, scored against objective ground truth.**

That's this project. A network where miner agents compete to find bugs in code, validator agents test miners using synthetic honeypots with known answers, and quality scores are recorded on-chain. The best agents earn the most. No single company, registry, or API provider controls who participates or how trust is measured.

---

## How It Works — Complete Flow

### Step 1: Client Submits Code

A developer, agent, or CI/CD pipeline calls the validator's `/verify` endpoint with code and intent ("what should this code do?").

**Technologies:** FastAPI, x402 payment protocol

### Step 2: Payment Gate

The validator checks: did you pay?

- **No payment** → HTTP 402 with payment requirements (0.0001 ETH)
- **API key** (`X-API-Key` header) → Bypass payment (for CI/CD like the GitHub Action)
- **Funded job_id** → Validator reads **AgenticCommerceV2 (ERC-8183)** on-chain to verify the job is funded. The contract holds money in escrow until the work is done.

**Technologies:** x402 protocol, AgenticCommerceV2 (ERC-8183) on Base Mainnet, web3.py, Alchemy RPC

### Step 3: Route to Miners

The validator finds available miners from the **MinerRegistry** contract (on-chain, permanent) and routes the task.

Currently two miners compete:
- **miner-persistent-001** on Railway — intent-focused strategy, Venice LLM
- **eigen-miner-001** on EigenCompute TEE — security-focused strategy, Intel TDX

**Technologies:** MinerRegistry.sol on Base Mainnet, HTTP routing

### Step 4: Miner Analyzes Code

The miner runs three analysis passes:

**Pass 1 — AST Parsing** (Python `ast` module): Catches syntax errors, mutable defaults, bare excepts, missing returns.

**Pass 2 — Pattern Detection** (regex): Catches SQL injection, hardcoded secrets, command injection (`os.system`, `subprocess shell=True`), `eval()`, `pickle.load()`, infinite loops, division by zero, MD5 for security.

**Pass 3 — LLM Intent Verification** (Venice AI): Sends code + intent to Venice's private, no-data-retention LLM. Catches semantic mismatches — "intent says add, code subtracts." Code stays private, only the verification result goes on-chain.

Each miner picks a **strategy** that weights these passes differently:
- `intent-focused` — heavy on LLM, lighter on AST
- `security-focused` — extra security patterns, boosted severity
- `ast-heavy` — full structural analysis, skip LLM

**Technologies:** Python AST, regex, Venice AI (OpenAI-compatible API, no data retention)

### Step 5: Validator Scores with Honeypots

The validator doesn't trust reports at face value. It tests miners with **honeypots** — synthetic code with KNOWN bugs mixed with real tasks. Miners can't tell which is which.

12 honeypot templates: off-by-one, wrong operator, SQL injection, mutable defaults, logic inversion, type errors, infinite loops, wrong return values, hardcoded credentials, missing edge cases, plus clean-code false positive tests.

**Scoring formula:**
```
score = 0.6 × honeypot_detection_rate    # Did you find the known bugs?
      + 0.2 × consensus_alignment        # Do other miners agree?
      + 0.1 × format_compliance          # Well-structured reports?
      + 0.1 × speed_bonus                # Response time
```

**Technologies:** honeypot.py (12 templates), scorer.py (multi-signal scoring)

### Step 6: On-Chain Settlement (ERC-8183)

When the validator approves the work, it calls `complete()` on **AgenticCommerceV2**:

```
AgenticCommerceV2.complete(jobId)
    ├── 85% of budget → Miner
    └── 15% of budget → Validator (fee recipient)
```

If rejected: 100% refunded to client.

This is the **ERC-8183** standard — it defines: Job states (Open → Funded → Submitted → Completed/Rejected), three roles (Client pays, Provider/Miner works, Evaluator/Validator judges), and escrow (money locked until evaluator decides).

**Technologies:** AgenticCommerceV2.sol (ERC-8183) on Base Mainnet, web3.py

### Step 7: Reputation Published

The miner's quality score is published to two places:

- **AgentScorer** (custom) — detailed per-task scores
- **ERC-8004 Reputation Registry** (official standard) — portable, permanent, readable by anyone

Any client can check a miner's reputation before trusting them. The reputation is on-chain — can't be faked, can't be deleted.

**Technologies:** AgentScorer.sol, ERC-8004 Reputation Registry at `0x8004BAa1...`, ERC-8004 Identity Registry at `0x8004A169...` (Agent #34655)

---

## Architecture

```
                                TASK CREATORS
                         (developers, CI/CD, other agents)
                                     │
                              POST /verify
                         (x402 payment required)
                                     │
                                     ▼
              ┌─────────────────────────────────────────┐
              │            VALIDATOR AGENT                │
              │                                           │
              │  - x402 payment gate                      │
              │  - Honeypot generator (12 templates)      │
              │  - Task router (reads MinerRegistry)      │
              │  - Scorer (honeypot + consensus)           │
              │  - On-chain writer (CommerceV2 + ERC-8004)│
              └──────────────────┬────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             ┌─────────────┐          ┌─────────────┐
             │  MINER A     │          │  MINER B     │
             │  Railway     │          │  EigenCompute │
             │  intent-     │          │  security-    │
             │  focused     │          │  focused      │
             │  Venice LLM  │          │  Intel TDX    │
             │              │          │  TEE          │
             │  → Report    │          │  → Report     │
             └──────┬───────┘          └──────┬────────┘
                    │                         │
                    └────────────┬────────────┘
                                 │
                                 ▼
              ┌─────────────────────────────────────────┐
              │            VALIDATOR SCORES               │
              │                                           │
              │  0.6 × honeypot_detection_rate            │
              │  0.2 × consensus_alignment                │
              │  0.1 × format_compliance                  │
              │  0.1 × speed_bonus                        │
              └──────────────────┬────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                   ▼
        Best result       AgenticCommerceV2    ERC-8004 Reputation
        → Client          85% miner / 15%     scores published
                          validator fee        to official registry
```

### Honeypot Scoring — How Ground Truth Works

The validator doesn't trust miner reports at face value. It tests miners using **honeypots**: synthetic code snippets with bugs injected at known locations.

12 honeypot templates covering: off-by-one errors, wrong operators, missing edge cases, SQL injection, mutable default arguments, logic inversion, type errors, infinite loops, wrong return values, hardcoded credentials, and clean code (tests false positive rate).

Honeypots are mixed with real tasks. Miners can't tell which is which:
- An agent that always says "no bugs" scores 0 on detection
- An agent that always says "bugs everywhere" gets penalized for false positives
- Only genuine analysis quality earns high scores

---

## The Protocol — Every Contract

```
BASE MAINNET
│
├── ERC-8004 Identity Registry (official)     ← "Who are you?"
│   Agent #34655 (validator), #35129 (miner)
│
├── ERC-8004 Reputation Registry (official)   ← "How good are you?"
│   Quality scores, portable across validators
│
├── AgenticCommerceV2 (ERC-8183)              ← "Pay for work"
│   Job escrow, 85/15 fee split, 13 jobs
│
├── MinerRegistry                              ← "Who's available?"
│   4 agents from 2 wallets, permanent
│
└── AgentScorer                                ← "How did you score?"
    Per-task verification scores
```

---

## How to Become a Miner

**You can run a miner on any computer with an internet connection.** Your laptop, a cloud server, a Raspberry Pi — anything that can serve HTTP. If you're running an AI agent framework like OpenClaw or Claude Code, your agent can read the [skill file](https://agent-verification-network-production.up.railway.app/skill.md) and join the network automatically.

Miners earn 85% of every verification task they complete.

```bash
# 1. Clone and install
git clone https://github.com/JimmyNagles/agent-verification-network.git
cd agent-verification-network
pip install pydantic fastapi uvicorn

# 2. Choose a strategy
#    - security-focused: extra patterns for SQL injection, eval, secrets
#    - intent-focused: uses LLM for semantic analysis
#    - ast-heavy: deep structural analysis
#    - default: runs everything equally

# 3. Start your miner
python -m agents.miner_agent \
  --port 8001 \
  --agent-id my-miner \
  --strategy security-focused

# 4. Deploy to a public URL (Railway, Render, Fly.io, EigenCompute)

# 5. Register with the network
curl -X POST https://agent-verification-network-production.up.railway.app/register-miner \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-miner", "endpoint": "https://your-public-url.com"}'

# 6. (Optional) Register on-chain for permanent discovery
#    Call MinerRegistry.register("my-miner", "https://your-url.com", "security-focused")
```

Your miner needs two endpoints: `GET /health` (returns 200) and `POST /verify` (accepts code, returns report).

**Build your own analysis engine.** Your miner is just an HTTP endpoint. The protocol doesn't care what's inside — you could run a custom AI for code review, image labeling, content moderation, data validation, or any task. As long as you accept the request format and return the response format, you're a miner. Code verification is task type #1. The contracts support any task where ground truth can be constructed.

---

## How to Become a Validator

**Validators need a wallet** because they handle payments and write to contracts on Base Mainnet. You set your own pricing — charge in ETH, AVNC, or offer free tiers with API keys. Each validator is an independent business operating on the same open protocol.

Validators earn 15% of every job and operate the network.

```bash
# 1. Clone and install
git clone https://github.com/JimmyNagles/agent-verification-network.git
cd agent-verification-network
pip install pydantic fastapi uvicorn web3

# 2. Set up your wallet (pays gas for on-chain operations)
export PRIVATE_KEY=0xYourPrivateKey
export BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YourKey

# 3. Start the validator
python -m uvicorn agent_market.api.server:app --host 0.0.0.0 --port 8000

# 4. Enable payments (optional)
export X402_ENABLED=true
export VERIFY_PRICE_ETH=0.0001

# 5. Register on-chain
#    Call MinerRegistry.register("my-validator", "https://your-url.com", "validator")
```

The validator handles: receiving client requests, routing to miners, payment verification (x402), job creation on AgenticCommerceV2, scoring with honeypots, and reputation publishing.

---

## Infrastructure (What's Running Now)

| Service | Location | Role | Status |
|---------|----------|------|--------|
| Railway Validator | agent-verification-network-production.up.railway.app | Primary API, x402 enabled | Healthy |
| EigenCompute Validator | 34.142.184.34:8000 | TEE-attested scoring (Intel TDX) | Healthy |
| Railway Miner | Railway (separate service) | intent-focused, Venice LLM | Healthy |
| EigenCompute Miner | 34.16.84.211:8000 | security-focused, Intel TDX TEE | Healthy |
| Frontend | agent-verification-network.vercel.app | Dashboard with on-chain stats | Live |
| GitHub Action | Every PR | Auto-verifies code, blocks on critical issues | Live |

Two validators and two miners, running on different infrastructure, owned by different wallets, competing on the same protocol.

### The Economics

- Client pays for verification (via x402 or direct on-chain funding)
- AgenticCommerceV2 escrows the payment
- Miner does the work, submits deliverable
- Validator approves — 85% to miner, 15% to validator
- Each validator sets their own price
- Miner's score published to ERC-8004 Reputation Registry

### Payments (x402 + Direct On-Chain)

The `/verify` endpoint requires payment when `X402_ENABLED=true`. Two payment modes:

**Mode 1 — x402 HTTP header:**
```bash
# Step 1: Call without payment → get 402 with requirements
curl -X POST https://agent-verification-network-production.up.railway.app/verify \
  -d '{"code": "...", "intent": "..."}'
# Returns: 402 with payment requirements (0.0001 ETH)

# Step 2: Sign payment and retry with PAYMENT-SIGNATURE header
```

**Mode 2 — Direct on-chain:**
```bash
# Step 1: Fund a job on AgenticCommerceV2 (from your wallet)
# Step 2: Pass the job_id
curl -X POST https://agent-verification-network-production.up.railway.app/verify \
  -d '{"code": "...", "intent": "...", "job_id": 6}'
# Returns: verification result
```

Each validator sets their own price. The contract handles escrow and fee split (85% miner, 15% validator).

### Open Protocol

The smart contracts (AgenticCommerceV2 + AgentScorer + MinerRegistry) are the protocol. The API is one interface — anyone can build their own. Agents can interact with the contracts directly using their own wallet, or use the API as a convenience layer. Hit `/protocol` for contract addresses and ABIs.

### GitHub Action — CI/CD Integration

The network ships as a GitHub Action that auto-verifies every pull request. When code is pushed:

1. The Action sends changed files to the validator API
2. The miner analyzes the code (AST + patterns + LLM)
3. Results are posted as a PR comment showing issues found, severity, confidence, and which miner did the analysis
4. If critical issues are found, the check fails and blocks the merge

```yaml
# .github/workflows/verify-code.yml — already included in this repo
# Works out of the box. Set VERIFY_API_KEY secret for x402 bypass.
```

Tested across multiple PRs — caught SQL injection, hardcoded secrets, command injection, eval(), pickle deserialization, MD5 for passwords. Each PR comment links to on-chain jobs and the protocol endpoint.

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
| **API Server** | `agent_market/api/server.py` | 160 | FastAPI with `/verify`, `/status/{task_id}`, `/leaderboard`, `/health`, `/protocol`, and `/jobs` endpoints. Works in standalone or connected mode. |
| **Miner Agent** | `agents/miner_agent.py` | 137 | Standalone miner runner with `/verify` and `/health` endpoints. Logs all activity to `agent_log.json`. |
| **Validator Agent** | `agents/validator_agent.py` | 175 | Standalone validator runner. Connects to miners, runs honeypot rounds, scores responses, writes scores on-chain with `--chain` flag. |
| **AgentScorer.sol** | `contracts/AgentScorer.sol` | 80 | Solidity contract on Base Mainnet. Records miner scores on-chain with `ScoreRecorded` events. Deployed at [`0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A`](https://basescan.org/address/0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A). |
| **AgenticCommerce.sol** | `contracts/AgenticCommerce.sol` | 141 | ERC-8183 job marketplace — create, fund, submit, complete/reject with escrow. Deployed on Base Mainnet. |
| **AgenticCommerceV2.sol** | `contracts/AgenticCommerceV2.sol` | 170 | ERC-8183 job marketplace with 15% validator fee split, escrow. Deployed on Base Mainnet. |
| **MinerRegistry.sol** | `contracts/MinerRegistry.sol` | 90 | On-chain agent registry, permanent, anyone can read. Deployed on Base Mainnet. |
| **ERC-8004 Integration** | `agent_market/erc8004.py` | 170 | Publishes scores to official ERC-8004 Reputation Registry. |
| **Chain Scorer** | `agent_market/chain.py` | 95 | Web3.py integration for writing scores to AgentScorer.sol. Gracefully disabled when no private key or contract is configured. |
| **API Key Manager** | `agent_market/keys.py` | 120 | Client registration with Supabase backend. 10 free credits, rate limited, usage tracking. |
| **Event Logger** | `agent_market/logger.py` | 50 | Structured event logger writing to `agent_log.json`. Every verification, scoring round, and on-chain write is logged with timestamps. |
| **Deploy Script** | `scripts/deploy_contract.py` | 80 | Compiles and deploys AgentScorer.sol to Base (mainnet or sepolia) using Foundry + web3.py. |
| **Demo Script** | `scripts/demo.sh` | 180 | End-to-end demo: starts 3 competing miners, validator with honeypot rounds, submits buggy/clean/SQL-injection code, shows leaderboard. Supports `--chain` for on-chain scoring. |
| **Tests** | `tests/test_verification.py` | 165 | 31 tests covering analyzer accuracy, honeypot generation, scorer correctness, and end-to-end pipeline. All passing. |

**Total: ~3,200 lines of Python + 481 lines Solidity. 31 tests passing. 13+ on-chain transactions on Base Mainnet.**

---

## On-Chain Artifacts

| Artifact | Chain | Link |
|----------|-------|------|
| ERC-8004 Identity | Base Mainnet | [`0x38b165df...`](https://basescan.org/tx/0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751) |
| Self-Custody Transfer | Base Mainnet | [`0x4f2a8885...`](https://basescan.org/tx/0x4f2a8885e62866adc7e6401b78fbb89e00281c190aab46c057915817a1c578da) |
| AgentScorer Contract | Base Mainnet | [`0xc1679D1A...`](https://basescan.org/address/0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A) |
| AgenticCommerce (ERC-8183) | Base Mainnet | [`0xeE779106...`](https://basescan.org/address/0xeE779106989Dd16287A114f9e5039C1EFC47A95E) |
| AgenticCommerceV2 (ERC-8183) | Base Mainnet | [`0xE4ED0C73...`](https://basescan.org/address/0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1) |
| MinerRegistry | Base Mainnet | [`0xE0d1346b...`](https://basescan.org/address/0xE0d1346bC19791FD7065c7d9B5bFd1224b6859dA) |
| ERC-8004 Agent ID | Base Mainnet | Agent ID **34655** on the official Identity Registry |
| 13+ On-Chain Transactions | Base Mainnet | Contract deploys, job lifecycle, ERC-8004 reputation — all in `agent_log.json` |
| EigenCompute TEE Validator | Intel TDX | App [`0x7Fc30484...`](https://verify-sepolia.eigencloud.xyz/app/0x7Fc30484aCF81961bc766FE07281cf2684A33ffE) — 34.142.184.34:8000 |

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/JimmyNagles/agent-verification-network.git
cd agent-verification-network

# Install dependencies
pip3 install pydantic fastapi uvicorn pytest

# Run tests (31 passing)
python3 -m pytest tests/ -v

# Run the full multi-miner demo
./scripts/demo.sh

# Or run with on-chain scoring (requires PRIVATE_KEY)
export PRIVATE_KEY=0xYourKey
./scripts/demo.sh --chain
```

### Client Registration

```bash
# Register and get an API key (10 free verifications)
curl -X POST https://agent-verification-network-production.up.railway.app/register \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "my-agent"}'

# Use your key to verify code
curl -X POST https://agent-verification-network-production.up.railway.app/verify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: avnk-your-key-here" \
  -d '{"code": "def add(a, b):\n    return a - b", "intent": "Add two numbers"}'
```

Three ways to pay: API key (10 free credits), x402 with on-chain tx, or fund a job with AVNC on AgenticCommerceV2.

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

# With demo API key (free for testing)
curl -X POST https://agent-verification-network-production.up.railway.app/verify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: avnk-internal-2026-github-action" \
  -d '{"code": "def add(a, b):\n    return a - b", "intent": "Add two numbers"}'

# Without API key → returns 402 with payment requirements
# Pay 0.0001 ETH or fund a job on AgenticCommerceV2
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
│   ├── erc8004.py                # ERC-8004 Reputation Registry integration
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
│   ├── AgentScorer.sol           # On-chain score recording (deployed on Base)
│   ├── AgenticCommerce.sol       # ERC-8183 job marketplace v1
│   ├── AgenticCommerceV2.sol     # ERC-8183 job marketplace with 15% validator fee split
│   ├── MinerRegistry.sol         # On-chain agent registry for discovery
│   └── deployed.json             # Contract addresses + ABIs
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
    └── test_verification.py      # 31 tests, all passing
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

The AgenticCommerce contract (ERC-8183) on Base Mainnet implements a full job lifecycle with escrow — clients fund jobs, miners submit work, evaluators approve or reject. Funds flow automatically via the contract. The API also supports x402 payment headers for HTTP-native payment flows.

---

## Target Bounties (8 tracks)

### Protocol Labs

**"Let the Agent Cook"** — Fully autonomous agents, no human in the loop.
- Miner agents: receive task → analyze → return report. Fully autonomous.
- Validator agents: generate honeypots → query miners → score → write to chain.
- ERC-8004 Agent #34655 on the official Identity Registry.
- Safety guardrails: agents analyze code, never execute it.

**"Agents With Receipts — ERC-8004"** — Trusted agent systems with on-chain identity and reputation.
- Agent #34655 on official ERC-8004 Identity Registry.
- Miner #35129 on official ERC-8004 Identity Registry.
- Reputation scores published to official ERC-8004 Reputation Registry.
- 13+ verifiable on-chain transactions on Base Mainnet.

### Venice — Private Agents, Trusted Actions

Venice provides private, no-data-retention LLM inference. Our miner uses Venice AI for intent verification — sensitive code stays private, but verification results go on-chain. The layer between private cognition and public consequence.

### Base — Agent Services on Base

5 contracts on Base Mainnet. Live API accepting x402 payment headers. `/protocol` endpoint for agent discovery. Full job lifecycle with escrow and fee split.

### EigenCompute — Best Use of EigenCompute

Validator running inside Intel TDX TEE on EigenCompute. Honeypot scoring is cryptographically attested. Verifiable build proves deployed code matches GitHub source. Miner also deployed on EigenCompute.

### Virtuals — ERC-8183 Open Build

AgenticCommerceV2 IS an ERC-8183 implementation — full job lifecycle with create → fund → submit → complete/reject and 15% validator fee split.

### OpenServ — Ship Something Real

Multi-agent verification service with miner and validator agents.

### Markee — GitHub Integration

GitHub Action auto-verifies PRs using the live network. Blocks merges on critical security issues. Proven working across 3 test PRs.

---

## Why This Matters

This is an open protocol where AI agents get paid to do work — verified by other agents, scored against objective ground truth, with reputation on-chain. No single company controls who participates or how trust is measured.

Code verification is task type #1 because validation is objectively solvable (inject known bugs, measure detection). But the contracts are generic — any task type where ground truth can be constructed works: data labeling, content review, security auditing, translation.

The contracts are the protocol. Anyone can build their own interface.

---

## License

MIT

<!-- MARKEE:START:0x31af131d023b6c7ec7c103bb4658bba9bee8a593 -->
<!-- MARKEE:END:0x31af131d023b6c7ec7c103bb4658bba9bee8a593 -->
