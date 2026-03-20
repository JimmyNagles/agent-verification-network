#!/usr/bin/env python3
"""
Miner Agent — Standalone runner for the code verification miner.

Starts a FastAPI server that accepts verification tasks from validators,
runs the analysis pipeline, and logs all activity to agent_log.json.

Usage:
    python -m agents.miner_agent [--port 8001] [--agent-id miner-001]
"""

import argparse
import asyncio
import logging
import sys
import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent_market.miner.analyzer import analyze_code
from agent_market.logger import log_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("miner-agent")


def create_app(agent_id: str) -> FastAPI:
    app = FastAPI(title=f"Miner Agent ({agent_id})")

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

        result = analyze_code(
            code=request.code,
            intent=request.intent,
            language=request.language,
            use_llm=False,
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
            "uptime": round(time.time() - stats["started_at"], 1),
            "tasks_completed": stats["tasks_completed"],
            "issues_found": stats["issues_found"],
        }

    # Log startup
    log_event(
        event_type="agent_started",
        agent_role="miner",
        agent_id=agent_id,
        details={"capabilities": ["ast_parsing", "pattern_detection", "security_analysis"]},
    )

    return app


def main():
    parser = argparse.ArgumentParser(description="Run a miner agent")
    parser.add_argument("--port", type=int, default=8001, help="Port to listen on")
    parser.add_argument("--agent-id", default=f"miner-{uuid4().hex[:8]}", help="Agent identifier")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    logger.info(f"Starting miner agent: {args.agent_id} on port {args.port}")

    app = create_app(args.agent_id)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
