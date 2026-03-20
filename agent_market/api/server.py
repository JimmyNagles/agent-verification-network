"""
Agent Verification Network — API Server

FastAPI endpoint for submitting code for verification by competing AI agents.

Two modes:
  - Standalone (default): Runs analysis directly using the local analyzer.
  - Connected: Routes tasks through the validator to competing miner agents.

Usage:
    uvicorn agent_market.api.server:app --host 0.0.0.0 --port 8000
"""

import asyncio
from typing import Optional
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from agent_market.x402 import check_x402_payment, get_pricing_info

app = FastAPI(
    title="Agent Verification Network",
    description="Decentralized code verification by competing AI agents",
    version="1.0.0",
)

# Validator reference — None means standalone/demo mode
_validator = None

# In-memory task storage
results = {}


def attach_validator(validator):
    """Attach a validator instance to route tasks through the agent network."""
    global _validator
    _validator = validator


def get_mode():
    """Return current operating mode."""
    return "connected" if _validator is not None else "standalone"


# ── Request/Response Models ──────────────────────────────────────

class VerifyRequest(BaseModel):
    code: str = Field(description="Source code to verify")
    intent: str = Field(description="What the code should do")
    language: str = Field(default="python", description="Programming language")


class VerifyResponse(BaseModel):
    task_id: str
    passed: bool
    confidence: float
    issues: list
    suggestions: list
    agent_id: Optional[str] = None
    score: Optional[float] = None
    mode: Optional[str] = None


class TaskStatus(BaseModel):
    task_id: str
    status: str  # "queued", "processing", "complete"
    result: Optional[VerifyResponse] = None


# ── Endpoints ────────────────────────────────────────────────────

@app.post("/verify", response_model=VerifyResponse)
async def verify_code(request: VerifyRequest, raw_request: Request = None):
    """
    Submit code for verification by the agent network.

    In connected mode, the task is routed through the validator to
    competing miner agents. In standalone mode, analysis runs locally.

    When x402 is enabled (X402_ENABLED=true), a valid PAYMENT-SIGNATURE
    header is required. Without it, returns 402 Payment Required.
    """
    # x402 payment gate
    if raw_request is not None:
        payment_response = await check_x402_payment(raw_request)
        if payment_response is not None:
            return payment_response
    if _validator is not None:
        task_id = _validator.add_task(
            code=request.code,
            intent=request.intent,
            language=request.language,
        )

        result = None
        for _ in range(60):
            result = _validator.get_result(task_id)
            if result is not None:
                break
            await asyncio.sleep(1)

        if result is None:
            from agent_market.miner.analyzer import analyze_code
            local_result = analyze_code(
                code=request.code,
                intent=request.intent,
                language=request.language,
            )
            response = VerifyResponse(
                task_id=task_id,
                passed=local_result["passed"],
                confidence=local_result["confidence"],
                issues=local_result["issues"],
                suggestions=local_result["suggestions"],
                mode="standalone_fallback",
            )
        else:
            response = VerifyResponse(
                task_id=task_id,
                passed=result["passed"],
                confidence=result["confidence"],
                issues=result["issues"],
                suggestions=result["suggestions"],
                agent_id=result.get("agent_id"),
                score=result.get("score"),
                mode="connected",
            )

        results[task_id] = response
        return response

    else:
        task_id = str(uuid4())

        from agent_market.miner.analyzer import analyze_code
        result = analyze_code(
            code=request.code,
            intent=request.intent,
            language=request.language,
        )

        response = VerifyResponse(
            task_id=task_id,
            passed=result["passed"],
            confidence=result["confidence"],
            issues=result["issues"],
            suggestions=result["suggestions"],
            mode="standalone",
        )

        results[task_id] = response
        return response


@app.get("/status/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Check the status of a submitted verification task."""
    if task_id in results:
        return TaskStatus(
            task_id=task_id,
            status="complete",
            result=results[task_id],
        )

    if _validator is not None:
        for task in _validator.task_queue:
            if task["task_id"] == task_id:
                return TaskStatus(task_id=task_id, status="queued")

    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/leaderboard")
async def get_leaderboard():
    """Top performing miner agents by score."""
    if _validator is not None:
        scores = _validator.scores
        miners = []
        for agent_id, score in scores.items():
            if score > 0:
                miners.append({"agent_id": agent_id, "score": round(float(score), 4)})
        miners.sort(key=lambda m: m["score"], reverse=True)
        return {"mode": "connected", "agents": miners[:20]}

    return {
        "mode": "standalone",
        "agents": [],
        "note": "No miners connected. Run ./scripts/demo.sh to start the multi-miner network.",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Agent Verification Network",
        "version": "1.0.0",
        "mode": get_mode(),
        "task_types": ["code_verification"],
        "tasks_completed": len(results),
    }


@app.get("/pricing")
async def pricing():
    """Return current verification pricing and x402 configuration."""
    return get_pricing_info()


@app.get("/")
async def root():
    return {
        "name": "Agent Verification Network",
        "description": "Decentralized code verification by competing AI agents",
        "mode": get_mode(),
        "endpoints": {
            "/verify": "POST — Submit code for verification",
            "/status/{task_id}": "GET — Check task status",
            "/leaderboard": "GET — Top performing agents",
            "/pricing": "GET — Verification pricing and x402 config",
            "/health": "GET — Health check",
        },
    }
