#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Agent Verification Network — End-to-End Demo
#
# Demonstrates the full verification pipeline:
#   1. Starts a miner agent
#   2. Starts a validator agent connected to the miner
#   3. Runs validation rounds (honeypot + real tasks)
#   4. Submits code for verification via the API
#   5. Shows the leaderboard
#
# Usage:
#   ./scripts/demo.sh
# ──────────────────────────────────────────────────────────────

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MINER_PORT=8001
VALIDATOR_PORT=8000
MINER_PID=""
VALIDATOR_PID=""

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down agents...${NC}"
    [ -n "$MINER_PID" ] && kill "$MINER_PID" 2>/dev/null && echo "  Miner stopped"
    [ -n "$VALIDATOR_PID" ] && kill "$VALIDATOR_PID" 2>/dev/null && echo "  Validator stopped"
    wait 2>/dev/null
    echo -e "${GREEN}Done.${NC}"
}
trap cleanup EXIT

echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Agent Verification Network — Live Demo          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Check dependencies ─────────────────────────────
echo -e "${YELLOW}[0/6] Checking dependencies...${NC}"
python3 -c "import fastapi, pydantic, uvicorn" 2>/dev/null || {
    echo -e "${RED}Missing dependencies. Install with: pip install -e '.[dev]'${NC}"
    exit 1
}
echo "  All dependencies found."
echo ""

# ── Step 1: Run tests ──────────────────────────────────────
echo -e "${YELLOW}[1/6] Running test suite...${NC}"
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
echo ""

# ── Step 2: Start miner agent ──────────────────────────────
echo -e "${YELLOW}[2/6] Starting miner agent on port ${MINER_PORT}...${NC}"
python3 -m agents.miner_agent --port "$MINER_PORT" --agent-id "demo-miner-001" &
MINER_PID=$!
sleep 2

# Check miner is up
if curl -s "http://localhost:${MINER_PORT}/health" > /dev/null 2>&1; then
    echo -e "  ${GREEN}Miner agent is running.${NC}"
else
    echo -e "  ${RED}Miner failed to start.${NC}"
    exit 1
fi
echo ""

# ── Step 3: Start validator with miner connected ───────────
echo -e "${YELLOW}[3/6] Starting validator agent on port ${VALIDATOR_PORT}...${NC}"
echo "  Connecting to miner at http://localhost:${MINER_PORT}"
python3 -m agents.validator_agent \
    --port "$VALIDATOR_PORT" \
    --agent-id "demo-validator-001" \
    --rounds 5 \
    --interval 2 \
    --miners "http://localhost:${MINER_PORT}" &
VALIDATOR_PID=$!
sleep 3

if curl -s "http://localhost:${VALIDATOR_PORT}/health" > /dev/null 2>&1; then
    echo -e "  ${GREEN}Validator agent is running.${NC}"
else
    echo -e "  ${RED}Validator failed to start.${NC}"
    exit 1
fi
echo ""

# ── Step 4: Submit code for verification ───────────────────
echo -e "${YELLOW}[4/6] Submitting buggy code for verification...${NC}"
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
echo -e "${YELLOW}[5/6] Submitting clean code for verification...${NC}"
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

# ── Step 6: Show results ──────────────────────────────────
echo -e "${YELLOW}[6/6] Fetching leaderboard and agent log...${NC}"
echo ""

# Wait for validation rounds to complete
echo "  Waiting for validation rounds to finish..."
sleep 12

echo -e "  ${CYAN}Leaderboard:${NC}"
curl -s "http://localhost:${VALIDATOR_PORT}/leaderboard" | python3 -m json.tool 2>/dev/null
echo ""

echo -e "  ${CYAN}Agent Log (last 5 events):${NC}"
python3 -c "
import json
with open('agent_log.json') as f:
    log = json.load(f)
events = log['events'][-5:]
for e in events:
    print(f\"  {e['timestamp']} | {e['type']:25s} | {e['agent_role']:10s} | {e['agent_id']}\")
    if 'details' in e:
        for k, v in e['details'].items():
            print(f\"    {k}: {v}\")
"
echo ""

echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Demo complete! Agents verified each other.      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
