#!/usr/bin/env python3
"""
Miner Agent — Standalone runner for the code verification miner.

Starts a FastAPI server that accepts verification tasks from validators,
runs the analysis pipeline, and logs all activity to agent_log.json.

Usage:
    python -m agents.miner_agent [--port 8001] [--agent-id miner-001]
    python -m agents.miner_agent [--port 8001] [--agent-id miner-001] [--strategy ast-heavy]
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent_market.miner.analyzer import analyze_code
from agent_market.logger import log_event
from agents.miner_strategies import run_strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("miner-agent")


def create_app(agent_id: str, strategy: str = "default") -> FastAPI:
    app = FastAPI(title=f"Miner Agent ({agent_id})")
    _strategy = strategy

    class VerifyRequest(BaseModel):
        code: str
        intent: str
        language: str = "python"
        task_id: str = ""

    class VerifyResponse(BaseModel):
        task_id: str
        issues: list = []
        confidence: float = 0.0
        passed: bool = True
        suggestions: list = []
        processing_time: float = 0.0
        agent_id: str = ""

    # Track stats
    stats = {"tasks_completed": 0, "issues_found": 0, "started_at": time.time()}

    @app.post("/verify", response_model=VerifyResponse)
    async def verify(request: VerifyRequest):
        task_id = request.task_id or str(uuid4())
        start = time.time()

        logger.info(f"Task {task_id}: analyzing {request.language} code")

        result = run_strategy(
            strategy=_strategy,
            code=request.code,
            intent=request.intent,
            language=request.language,
        )

        elapsed = time.time() - start
        stats["tasks_completed"] += 1
        stats["issues_found"] += len(result["issues"])

        log_event(
            event_type="verification_completed",
            agent_role="miner",
            agent_id=agent_id,
            details={
                "task_id": task_id,
                "issues_found": len(result["issues"]),
                "confidence": result["confidence"],
                "passed": result["passed"],
                "processing_time": round(elapsed, 3),
            },
        )

        logger.info(
            f"Task {task_id}: {len(result['issues'])} issues, "
            f"confidence={result['confidence']:.2f}, time={elapsed:.2f}s"
        )

        return VerifyResponse(
            task_id=task_id,
            issues=result["issues"],
            confidence=result["confidence"],
            passed=result["passed"],
            suggestions=result["suggestions"],
            processing_time=elapsed,
            agent_id=agent_id,
        )

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "agent_id": agent_id,
            "role": "miner",
            "strategy": _strategy,
            "uptime": round(time.time() - stats["started_at"], 1),
            "tasks_completed": stats["tasks_completed"],
            "issues_found": stats["issues_found"],
        }

    # Log startup
    log_event(
        event_type="agent_started",
        agent_role="miner",
        agent_id=agent_id,
        details={
            "capabilities": ["ast_parsing", "pattern_detection", "security_analysis"],
            "strategy": _strategy,
        },
    )

    return app


def auto_register(validator_url: str, agent_id: str, my_url: str, strategy: str):
    """Auto-register with the validator after startup."""
    import urllib.request
    import json as _json
    import threading

    def _register():
        time.sleep(10)  # Wait for both services to be ready
        registered = False
        while not registered:
            try:
                data = _json.dumps({
                    "agent_id": agent_id,
                    "endpoint": my_url,
                    "strategy": strategy,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{validator_url.rstrip('/')}/register-miner",
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "AgentVerificationNetwork/1.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = _json.loads(resp.read().decode("utf-8"))
                    logger.info(f"Registered with validator: {result}")
                    registered = True
            except Exception as e:
                logger.warning(f"Auto-registration failed: {e} — retrying in 30s")
                time.sleep(30)

    thread = threading.Thread(target=_register, daemon=True)
    thread.start()


def main():
    parser = argparse.ArgumentParser(description="Run a miner agent")
    parser.add_argument("--port", type=int, default=8001, help="Port to listen on")
    parser.add_argument("--agent-id", default=f"miner-{uuid4().hex[:8]}", help="Agent identifier")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument(
        "--strategy",
        choices=["ast-heavy", "security-focused", "intent-focused", "default"],
        default="default",
        help="Analysis strategy (default: run all passes identically)",
    )
    args = parser.parse_args()

    # Check for auto-registration env vars
    validator_url = os.environ.get("VALIDATOR_URL", "")
    my_url = os.environ.get("MINER_PUBLIC_URL", "")

    logger.info(f"Starting miner agent: {args.agent_id} on port {args.port} (strategy={args.strategy})")

    app = create_app(args.agent_id, strategy=args.strategy)

    # Auto-register with validator if configured
    if validator_url and my_url:
        logger.info(f"Will auto-register with validator at {validator_url}")
        auto_register(validator_url, args.agent_id, my_url, args.strategy)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
