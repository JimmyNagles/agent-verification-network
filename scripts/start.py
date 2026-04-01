#!/usr/bin/env python3
"""Startup script — runs as manager or worker based on ROLE env var."""
import os
import subprocess
import sys

role = os.environ.get("ROLE", "manager")
port = os.environ.get("PORT", "8000")
agent_id = os.environ.get("AGENT_ID", "agent-001")
strategy = os.environ.get("STRATEGY", "default")

if role in ("miner", "worker"):
    cmd = [
        sys.executable, "-m", "agents.worker_agent",
        "--port", port,
        "--agent-id", agent_id,
        "--strategy", strategy,
        "--host", "0.0.0.0",
    ]
else:
    cmd = [
        "uvicorn", "agent_market.api.server:app",
        "--host", "0.0.0.0",
        "--port", port,
    ]

print(f"Starting as {role}: {' '.join(cmd)}")
subprocess.run(cmd)
