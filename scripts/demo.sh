#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Agent Verification Network — End-to-End Demo
#
# Demonstrates the full verification pipeline:
#   1. Starts 3 competing miner agents
#   2. Starts a validator agent connected to all miners
#   3. Runs validation rounds (honeypot + real tasks)
#   4. Submits code for verification via the API
#   5. Shows the leaderboard with ranked miners
#
# Usage:
#   ./scripts/demo.sh              # Standalone mode (no chain)
#   ./scripts/demo.sh --chain      # With on-chain scoring (needs PRIVATE_KEY)
# ──────────────────────────────────────────────────────────────

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VALIDATOR_PORT=8000
CHAIN_FLAG=""
PIDS=()

# Parse args
if [ "$1" = "--chain" ]; then
    CHAIN_FLAG="--chain"
    if [ -z "$PRIVATE_KEY" ]; then
        echo "ERROR: --chain requires PRIVATE_KEY env var"
        exit 1
    fi
fi

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down agents...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null && echo "  Stopped PID $pid"
    done
    wait 2>/dev/null
    echo -e "${GREEN}Done.${NC}"
}
trap cleanup EXIT

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Agent Verification Network — Multi-Miner Live Demo   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Check dependencies ─────────────────────────────
echo -e "${YELLOW}[0/7] Checking dependencies...${NC}"
python3 -c "import fastapi, pydantic, uvicorn" 2>/dev/null || {
    echo -e "${RED}Missing dependencies. Install with: pip install fastapi uvicorn pydantic${NC}"
    exit 1
}
echo "  All dependencies found."
echo ""

# ── Step 1: Run tests ──────────────────────────────────────
echo -e "${YELLOW}[1/7] Running test suite...${NC}"
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
echo ""

# ── Step 2: Start 3 competing miner agents (different strategies) ──
echo -e "${YELLOW}[2/7] Starting 3 competing miner agents with diverse strategies...${NC}"

# Each miner uses a different analysis strategy so they produce different results
STRATEGIES=("ast-heavy" "security-focused" "intent-focused")

for i in 1 2 3; do
    PORT=$((8000 + i))
    STRAT="${STRATEGIES[$((i-1))]}"
    python3 -m agents.miner_agent --port "$PORT" --agent-id "miner-00${i}" --strategy "$STRAT" &
    PIDS+=($!)
    echo "  Miner miner-00${i} starting on port ${PORT} (strategy: ${STRAT})..."
done
sleep 3

# Verify all miners are up
ALL_UP=true
for i in 1 2 3; do
    PORT=$((8000 + i))
    if curl -s "http://localhost:${PORT}/health" > /dev/null 2>&1; then
        echo -e "  ${GREEN}miner-00${i} (port ${PORT}) — running${NC}"
    else
        echo -e "  ${RED}miner-00${i} (port ${PORT}) — FAILED${NC}"
        ALL_UP=false
    fi
done
if [ "$ALL_UP" = false ]; then exit 1; fi
echo ""

# ── Step 3: Start validator connected to all miners ────────
echo -e "${YELLOW}[3/7] Starting validator agent on port ${VALIDATOR_PORT}...${NC}"
echo "  Connecting to 3 miners for competitive scoring"

python3 -m agents.validator_agent \
    --port "$VALIDATOR_PORT" \
    --agent-id "demo-validator-001" \
    --rounds 8 \
    --interval 2 \
    --miners "http://localhost:8001" "http://localhost:8002" "http://localhost:8003" \
    $CHAIN_FLAG &
PIDS+=($!)
sleep 3

if curl -s "http://localhost:${VALIDATOR_PORT}/health" > /dev/null 2>&1; then
    echo -e "  ${GREEN}Validator agent is running.${NC}"
    if [ -n "$CHAIN_FLAG" ]; then
        echo -e "  ${CYAN}On-chain scoring ENABLED (Base Sepolia)${NC}"
    fi
else
    echo -e "  ${RED}Validator failed to start.${NC}"
    exit 1
fi
echo ""

# ── Step 4: Submit buggy code for verification ─────────────
echo -e "${YELLOW}[4/7] Submitting buggy code for verification...${NC}"
echo ""
echo "  Code: def add(a, b): return a - b"
echo "  Intent: Add two numbers"
echo ""

RESULT=$(curl -s -X POST "http://localhost:${VALIDATOR_PORT}/verify" \
    -H "Content-Type: application/json" \
    -d '{
        "code": "def add(a, b):\n    return a - b",
        "intent": "Add two numbers and return the result",
        "language": "python"
    }')

echo -e "  ${GREEN}Verification result:${NC}"
echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"
echo ""

# ── Step 5: Submit clean code ──────────────────────────────
echo -e "${YELLOW}[5/7] Submitting clean code for verification...${NC}"
echo ""
echo "  Code: def add(a, b): return a + b"
echo "  Intent: Add two numbers"
echo ""

RESULT2=$(curl -s -X POST "http://localhost:${VALIDATOR_PORT}/verify" \
    -H "Content-Type: application/json" \
    -d '{
        "code": "def add(a, b):\n    return a + b",
        "intent": "Add two numbers and return the result",
        "language": "python"
    }')

echo -e "  ${GREEN}Verification result:${NC}"
echo "$RESULT2" | python3 -m json.tool 2>/dev/null || echo "$RESULT2"
echo ""

# ── Step 6: Submit SQL injection code ──────────────────────
echo -e "${YELLOW}[6/7] Submitting SQL injection vulnerability...${NC}"
echo ""
echo '  Code: def get_user(name): query = f"SELECT * FROM users WHERE name={name}"'
echo "  Intent: Safely query user by name"
echo ""

RESULT3=$(curl -s -X POST "http://localhost:${VALIDATOR_PORT}/verify" \
    -H "Content-Type: application/json" \
    -d '{
        "code": "def get_user(name):\n    query = f\"SELECT * FROM users WHERE name={name}\"\n    return db.execute(query)",
        "intent": "Safely query a user from the database by name",
        "language": "python"
    }')

echo -e "  ${GREEN}Verification result:${NC}"
echo "$RESULT3" | python3 -m json.tool 2>/dev/null || echo "$RESULT3"
echo ""

# ── Step 7: Show results ──────────────────────────────────
echo -e "${YELLOW}[7/7] Fetching leaderboard and agent log...${NC}"
echo ""

# Wait for validation rounds to complete
echo "  Waiting for validation rounds to finish..."
sleep 16

echo -e "  ${CYAN}Leaderboard (3 competing miners):${NC}"
curl -s "http://localhost:${VALIDATOR_PORT}/leaderboard" | python3 -m json.tool 2>/dev/null
echo ""

echo -e "  ${CYAN}Agent Log (last 8 events):${NC}"
python3 -c "
import json
with open('agent_log.json') as f:
    log = json.load(f)
events = log['events'][-8:]
for e in events:
    line = f\"  {e['timestamp']} | {e['type']:25s} | {e['agent_role']:10s} | {e['agent_id']}\"
    print(line)
    if 'details' in e:
        d = e['details']
        for k, v in d.items():
            if k == 'on_chain':
                print(f\"    {k}:\")
                for ck, cv in v.items():
                    print(f\"      {ck}: {cv}\")
            else:
                print(f\"    {k}: {v}\")
"
echo ""

echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Demo complete! 3 miners competed, scores recorded.   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
