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
import logging
import urllib.request
from typing import Optional
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from agent_market.logger import log_event
from agent_market.x402 import check_x402_payment, get_pricing_info

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agent Verification Network",
    description="Decentralized code verification by competing AI agents",
    version="1.0.0",
)

# Validator reference — None means standalone/demo mode
_validator = None

# In-memory task storage
results = {}

# In-memory registries for open network registration
_registered_miners: list[dict] = []
_registered_validators: list[dict] = []
_total_verifications: int = 0


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


class RegisterMinerRequest(BaseModel):
    agent_id: str = Field(description="Unique identifier for the miner agent")
    endpoint: str = Field(description="Base URL of the miner (must expose /health)")
    strategy: Optional[str] = Field(default=None, description="Optional analysis strategy description")


class RegisterMinerResponse(BaseModel):
    registered: bool
    agent_id: str
    total_miners: int


class RegisterValidatorRequest(BaseModel):
    validator_id: str = Field(description="Unique identifier for the validator agent")
    endpoint: str = Field(description="Base URL of the validator")


class RegisterValidatorResponse(BaseModel):
    registered: bool
    validator_id: str


class NetworkStatus(BaseModel):
    validators: list
    miners: list
    total_verifications: int
    mode: str


# ── Endpoints ────────────────────────────────────────────────────

@app.post("/verify")
async def verify_code(request: VerifyRequest, raw_request: Request = None):
    """
    Submit code for verification by the agent network.

    When x402 is enabled (X402_ENABLED=true), a valid payment is required.
    In connected mode, the task is routed through the validator to
    competing miner agents. In standalone mode, analysis runs locally.
    """
    # x402 payment gate
    if raw_request:
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


@app.post("/register-miner", response_model=RegisterMinerResponse)
async def register_miner(request: RegisterMinerRequest):
    """
    Register a miner agent to join the verification network.

    The miner's endpoint must expose a /health route that returns HTTP 200.
    If a validator is attached, the miner is also registered with it for
    task distribution. Otherwise the miner is tracked in standalone mode.
    """
    # Validate that the miner endpoint is reachable
    health_url = request.endpoint.rstrip("/") + "/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Miner health check returned status {resp.status}",
                )
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reach miner at {health_url}: {e}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Health check failed for {health_url}: {e}",
        )

    # Register with the validator if one is attached
    if _validator is not None:
        _validator.register_miner(request.agent_id, request.endpoint)

    # Always store in the in-memory registry
    entry = {
        "agent_id": request.agent_id,
        "endpoint": request.endpoint,
        "strategy": request.strategy,
    }
    _registered_miners.append(entry)

    log_event(
        event_type="miner_registered",
        agent_role="miner",
        agent_id=request.agent_id,
        details={"endpoint": request.endpoint, "strategy": request.strategy},
    )

    logger.info(f"Registered miner {request.agent_id} at {request.endpoint}")

    return RegisterMinerResponse(
        registered=True,
        agent_id=request.agent_id,
        total_miners=len(_registered_miners),
    )


@app.post("/register-validator", response_model=RegisterValidatorResponse)
async def register_validator(request: RegisterValidatorRequest):
    """
    Register a validator agent in the network registry.

    Validators are tracked in an in-memory list so the /network endpoint
    can report who is participating.
    """
    entry = {
        "validator_id": request.validator_id,
        "endpoint": request.endpoint,
    }
    _registered_validators.append(entry)

    log_event(
        event_type="validator_registered",
        agent_role="validator",
        agent_id=request.validator_id,
        details={"endpoint": request.endpoint},
    )

    logger.info(f"Registered validator {request.validator_id} at {request.endpoint}")

    return RegisterValidatorResponse(
        registered=True,
        validator_id=request.validator_id,
    )


@app.get("/network", response_model=NetworkStatus)
async def get_network():
    """Return the current state of the verification network."""
    return NetworkStatus(
        validators=list(_registered_validators),
        miners=list(_registered_miners),
        total_verifications=len(results),
        mode=get_mode(),
    )


@app.get("/pricing")
async def pricing():
    """Return current verification pricing and x402 configuration."""
    return get_pricing_info()


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


@app.get("/skill.md")
async def skill_file():
    """Machine-readable skill file for agents to join the network."""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    skill_path = Path(__file__).parent.parent.parent / "web" / "public" / "skill.md"
    if skill_path.exists():
        return PlainTextResponse(skill_path.read_text(), media_type="text/markdown")
    # Fallback: return a minimal skill file
    return PlainTextResponse(
        "# Agent Verification Network\n\n"
        "Join the network: POST /register-miner with {agent_id, endpoint}\n"
        "Verify code: POST /verify with {code, intent, language}\n"
        f"Base URL: https://agent-verification-network-production.up.railway.app\n"
        "Full docs: https://github.com/JimmyNagles/agent-verification-network\n",
        media_type="text/markdown",
    )


@app.get("/")
async def root():
    return {
        "name": "Agent Verification Network",
        "description": "Decentralized code verification by competing AI agents",
        "mode": get_mode(),
        "skill_file": "/skill.md",
        "endpoints": {
            "/verify": "POST — Submit code for verification",
            "/status/{task_id}": "GET — Check task status",
            "/leaderboard": "GET — Top performing agents",
            "/register-miner": "POST — Register a miner agent",
            "/register-validator": "POST — Register a validator agent",
            "/network": "GET — View network state",
            "/pricing": "GET — Verification pricing and x402 config",
            "/skill.md": "GET — Machine-readable skill file for agents",
            "/health": "GET — Health check",
        },
    }
