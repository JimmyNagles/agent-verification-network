# Build Plan — Agent Verification Network

> What needs to be built, in what order, using what technology.

---

## Status: What Works Right Now

```bash
# Install + run tests
pip3 install pydantic fastapi uvicorn pytest pytest-asyncio httpx
python3 -m pytest tests/ -v        # 14/14 passing

# Run API server
python3 -m uvicorn agent_market.api.server:app --port 8000

# Test it
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{"code": "def add(a, b):\n    return a - b", "intent": "Add two numbers"}'
```

The full analysis pipeline works in standalone mode: submit code → analyze → return report.

---

## What Needs to Be Built

### Phase 1: On-Chain Identity (ERC-8004 on Base)

**Goal:** Register miner and validator agents with on-chain identity.

**Technology:** ERC-8004 standard on Base Mainnet. The Synthesis hackathon creates an ERC-8004 identity at registration (`POST https://synthesis.devfolio.co/register`).

**What to build:**
- Register the project via Synthesis API (returns API key + ERC-8004 identity)
- Link agent identity to agent.json manifest
- Populate `agent.json.identity.registration` with the on-chain address

**Protocol Labs requirement:** Both "Let the Agent Cook" and "Agents With Receipts" require ERC-8004 integration with real on-chain transactions.

---

### Phase 2: AgentScorer Smart Contract (Solidity on Base)

**Goal:** Record miner verification scores on-chain so reputation is portable and verifiable.

**What the contract does:**
```
AgentScorer.sol
├── registerAgent(agentId, endpoint)     — register a miner agent
├── recordScore(agentId, taskId, score)  — validator writes a score after each round
├── getScore(agentId) → uint256          — get an agent's cumulative score
├── getLeaderboard() → Agent[]           — top agents by score
└── Events: AgentRegistered, ScoreRecorded
```

**Technology:**
- Solidity ^0.8.20
- Deploy to Base Sepolia (testnet) or Base Mainnet
- Use Foundry or Hardhat for deployment
- Call from Python validator via web3.py

**Key design:**
- Only the validator address can call `recordScore()` (access control)
- Scores are cumulative — each round adds to the agent's reputation
- All score writes emit events for indexing

---

### Phase 3: Locus USDC Payment Integration

**Goal:** Task creators pay for verification in USDC. Miner agents earn USDC for quality work.

**Technology:** Locus payment API on Base (`https://beta-api.paywithlocus.com/api`)

**Flow:**
```
1. Register with Locus API → get wallet + API key
   POST /api/register

2. Fund wallet with USDC on Base (or request hackathon credits)
   POST /api/gift-code-requests

3. Task creator submits code + pays:
   POST /verify  →  deducts USDC from task creator's Locus wallet

4. Validator scores miners, best miner earns:
   POST /api/pay/send  →  sends USDC to winning miner's wallet

5. All transactions on-chain and auditable:
   GET /api/pay/transactions
```

**What to build:**
- Locus client wrapper in Python (register, check balance, send, receive)
- Payment deduction on task submission
- Payment distribution to winning miner after scoring
- Transaction logging to `agent_log.json`

**Locus bounty requirement:** "Working Locus integration, Locus must be core to product, Base chain, USDC only."

---

### Phase 4: Agent Entry Points

**Goal:** Standalone scripts that run miner and validator agents autonomously.

**`agents/miner_agent.py`:**
```
1. Load ERC-8004 identity
2. Start FastAPI server on configured port
3. Listen for verification requests from validators
4. Run analysis pipeline on each request
5. Return structured audit reports
6. Log all actions to agent_log.json
```

**`agents/validator_agent.py`:**
```
1. Load ERC-8004 identity
2. Register on AgentScorer contract
3. Start validation loop:
   a. Generate honeypot (30% of rounds) or pull real task from queue
   b. Send to all registered miners via HTTP
   c. Score responses
   d. Write scores to AgentScorer contract on Base
   e. If real task: return best result to task creator
   f. If Locus enabled: send USDC to winning miner
4. Log all actions (including tx hashes) to agent_log.json
```

---

### Phase 5: Demo + Submission

**Goal:** End-to-end demo that an agent judge can verify.

**`scripts/demo.sh`:**
```bash
# 1. Start miner agent
python3 agents/miner_agent.py &

# 2. Start validator agent
python3 agents/validator_agent.py &

# 3. Submit clean code — should pass
curl -X POST http://localhost:8000/verify \
  -d '{"code": "def factorial(n):\n    if n == 0: return 1\n    return n * factorial(n-1)", "intent": "Return factorial"}'

# 4. Submit buggy code — should catch the bug
curl -X POST http://localhost:8000/verify \
  -d '{"code": "def add(a, b):\n    return a - b", "intent": "Add two numbers"}'

# 5. Show leaderboard (miner scores)
curl http://localhost:8000/leaderboard

# 6. Show on-chain score (Base)
# cast call $AGENT_SCORER "getScore(address)" $MINER_ADDRESS --rpc-url $BASE_RPC

# 7. Show agent_log.json with tx hashes
cat agent_log.json | python3 -m json.tool
```

**Submission checklist:**
- [ ] `agent.json` manifest with ERC-8004 registration populated
- [ ] `agent_log.json` with real tx hashes from Base
- [ ] `conversationLog.md` documenting the full build journey
- [ ] All code open-source on GitHub
- [ ] README maps to bounty criteria
- [ ] Tests passing
- [ ] Working demo (API callable, scores on-chain)

---

## Build Order

```
Phase 1: ERC-8004 Identity          ← Do first (unlocks Protocol Labs bounties)
    ↓
Phase 2: AgentScorer Contract       ← On-chain scoring (the core differentiator)
    ↓
Phase 3: Locus Payments             ← Unlocks Locus bounty, adds economic layer
    ↓
Phase 4: Agent Entry Points         ← Wire everything together
    ↓
Phase 5: Demo + Submission          ← Polish, test, submit
```

---

## Key Dependencies

| What | Where | Notes |
|------|-------|-------|
| ERC-8004 registration | Synthesis API | `curl -s https://synthesis.md/skill.md` |
| Base RPC | Alchemy / Infura / public | For contract deployment + reads |
| Locus API | `https://beta-api.paywithlocus.com/api` | Register → get wallet + API key |
| Solidity tooling | Foundry (`forge`) or Hardhat | For AgentScorer deployment |
| web3.py | pip install | For Python → Base chain interaction |
| USDC on Base | Locus hackathon credits | `POST /api/gift-code-requests` |
