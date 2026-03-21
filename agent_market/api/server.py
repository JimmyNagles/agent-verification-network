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
from agent_market.storage import store_on_filecoin
from agent_market.commerce import CommerceClient
from agent_market.registry import RegistryClient
from agent_market.erc8004 import ERC8004Client, OUR_AGENT_ID

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agent Verification Network",
    description="Decentralized code verification by competing AI agents",
    version="1.0.0",
)

# CORS — allow frontends and agents to call the API from any origin
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validator reference — None means standalone/demo mode
_validator = None

# Commerce client for on-chain job lifecycle
_commerce = CommerceClient()

# On-chain miner registry
_registry = RegistryClient()

# Official ERC-8004 reputation publishing
_erc8004 = ERC8004Client()

# In-memory task storage
results = {}

# In-memory registries for open network registration
_registered_miners: list[dict] = []
_registered_validators: list[dict] = []
_total_verifications: int = 0


async def _store_filecoin_background(task_id: str, response):
    """Fire-and-forget Filecoin storage so it doesn't block the API response."""
    try:
        storage = await store_on_filecoin(
            data=response.model_dump(),
            filename=f"verification_{task_id}.json",
        )
        if storage:
            response.filecoin_cid = storage["cid"]
            response.filecoin_url = storage["url"]
            results[task_id] = response  # Update with CID
    except Exception:
        pass


def _create_job_background(task_id: str, response):
    """Create an on-chain job for this verification task (fire-and-forget)."""
    import hashlib
    import threading

    def _do():
        try:
            # Hash the task_id as the job description
            desc_hash = hashlib.sha256(task_id.encode()).digest()
            job_result = _commerce.create_job(description_hash=desc_hash)
            if job_result:
                response.job_id = job_result["job_id"]
                response.job_tx = job_result["tx_hash"]
                results[task_id] = response

                log_event(
                    event_type="job_created",
                    agent_role="system",
                    agent_id="commerce",
                    details={
                        "task_id": task_id,
                        "job_id": job_result["job_id"],
                        "tx_hash": job_result["tx_hash"],
                        "block_number": job_result["block_number"],
                        "chain": job_result["chain"],
                        "contract": job_result["contract"],
                    },
                )
        except Exception as e:
            logger.warning(f"Background job creation failed: {e}")

    if _commerce.enabled:
        threading.Thread(target=_do, daemon=True).start()


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
    filecoin_cid: Optional[str] = None
    filecoin_url: Optional[str] = None
    job_id: Optional[int] = None
    job_tx: Optional[str] = None


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

        import os
        import json as _json

        best_result = None
        best_agent = None
        mode = "standalone"

        # If miners are registered, route to them
        if _registered_miners:
            miner_responses = []
            for miner in _registered_miners:
                try:
                    data = _json.dumps({
                        "code": request.code,
                        "intent": request.intent,
                        "language": request.language,
                        "task_id": task_id,
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"{miner['endpoint'].rstrip('/')}/verify",
                        data=data,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "AgentVerificationNetwork/1.0",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        miner_result = _json.loads(resp.read().decode("utf-8"))
                        miner_responses.append({
                            "agent_id": miner["agent_id"],
                            "result": miner_result,
                        })
                        logger.info(f"Miner {miner['agent_id']} responded: {len(miner_result.get('issues', []))} issues")
                except Exception as e:
                    logger.warning(f"Miner {miner['agent_id']} failed: {e}")

            # Pick the best response (highest confidence)
            if miner_responses:
                best = max(miner_responses, key=lambda r: r["result"].get("confidence", 0))
                best_result = best["result"]
                best_agent = best["agent_id"]
                mode = "network"
                logger.info(f"Best response from {best_agent} (confidence: {best_result.get('confidence')})")

        # Fallback to local analysis if no miners responded
        if best_result is None:
            from agent_market.miner.analyzer import analyze_code
            use_llm = os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes")
            best_result = analyze_code(
                code=request.code,
                intent=request.intent,
                language=request.language,
                use_llm=use_llm,
            )

        response = VerifyResponse(
            task_id=task_id,
            passed=best_result.get("passed", best_result.get("passed", True)),
            confidence=best_result.get("confidence", 0),
            issues=best_result.get("issues", []),
            suggestions=best_result.get("suggestions", []),
            agent_id=best_agent,
            mode=mode,
        )

        results[task_id] = response

        # Store report on Filecoin in background (fire-and-forget)
        asyncio.ensure_future(_store_filecoin_background(task_id, response))

        # Create on-chain job record (fire-and-forget)
        _create_job_background(task_id, response)

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

    # Also register on-chain (fire-and-forget)
    import threading
    def _register_onchain():
        result = _registry.register_miner(request.agent_id, request.endpoint, request.strategy or "")
        if result and not result.get("already_registered"):
            log_event(
                event_type="miner_registered_onchain",
                agent_role="miner",
                agent_id=request.agent_id,
                details={"tx_hash": result.get("tx_hash"), "chain": result.get("chain")},
            )
    if _registry.enabled:
        threading.Thread(target=_register_onchain, daemon=True).start()

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
    # Merge in-memory miners with on-chain registry
    all_miners = list(_registered_miners)
    onchain_miners = _registry.get_active_miners()
    # Add on-chain miners not already in memory
    known_ids = {m["agent_id"] for m in all_miners}
    for m in onchain_miners:
        if m["agent_id"] not in known_ids:
            all_miners.append(m)

    return NetworkStatus(
        validators=list(_registered_validators),
        miners=all_miners,
        total_verifications=len(results),
        mode=get_mode(),
    )


@app.get("/pricing")
async def pricing():
    """Return current verification pricing and x402 configuration."""
    return get_pricing_info()


@app.get("/jobs")
async def get_jobs():
    """On-chain job status from AgenticCommerce contract."""
    job_count = _commerce.get_job_count()
    return {
        "commerce_enabled": _commerce.enabled,
        "contract": _commerce.contract.address if _commerce.enabled else None,
        "chain": "base-mainnet" if _commerce.enabled and _commerce.chain_id == 8453 else "base-sepolia" if _commerce.enabled else None,
        "total_jobs": job_count,
        "explorer": f"https://basescan.org/address/{_commerce.contract.address}" if _commerce.enabled else None,
    }


@app.get("/stats")
async def get_stats():
    """On-chain stats from all contracts — the real numbers."""
    return {
        "miners_onchain": _registry.get_miner_count() if _registry.enabled else 0,
        "validators": len(_registered_validators) + 2,  # Railway + EigenCompute + any registered
        "jobs_onchain": _commerce.get_job_count() if _commerce.enabled else 0,
        "verifications": len(results),
        "chain": "base-mainnet",
        "registry_enabled": _registry.enabled,
        "commerce_enabled": _commerce.enabled,
    }


@app.get("/activity")
async def get_activity():
    """Recent network activity — verifications, registrations, on-chain events."""
    activity = []

    # Recent verifications
    for task_id, result in list(results.items())[-10:]:
        activity.append({
            "type": "verification",
            "task_id": task_id,
            "passed": result.passed,
            "confidence": result.confidence,
            "issues": len(result.issues),
            "agent_id": result.agent_id,
            "mode": result.mode,
        })

    # Registered miners
    for miner in _registered_miners[-5:]:
        activity.append({
            "type": "miner_registered",
            "agent_id": miner["agent_id"],
            "strategy": miner.get("strategy"),
        })

    # On-chain miners from registry
    onchain_miners = _registry.get_active_miners() if _registry.enabled else []
    for m in onchain_miners[-5:]:
        activity.append({
            "type": "miner_onchain",
            "agent_id": m["agent_id"],
            "strategy": m.get("strategy", ""),
        })

    return {
        "activity": activity,
        "total_verifications": len(results),
        "total_miners": len(_registered_miners) + len(onchain_miners),
    }


@app.get("/agents")
async def list_agents():
    """All registered agents with on-chain data — miners from registry, their endpoints, strategies."""
    agents = []

    # On-chain miners from MinerRegistry
    onchain_miners = _registry.get_active_miners() if _registry.enabled else []
    for m in onchain_miners:
        agents.append({
            "agent_id": m["agent_id"],
            "role": "miner",
            "endpoint": m["endpoint"],
            "strategy": m.get("strategy", ""),
            "owner": m.get("owner", ""),
            "registered_at": m.get("registered_at", 0),
            "source": "on-chain (MinerRegistry)",
        })

    # In-memory miners not on-chain
    known_ids = {a["agent_id"] for a in agents}
    for m in _registered_miners:
        if m["agent_id"] not in known_ids:
            agents.append({
                "agent_id": m["agent_id"],
                "role": "miner",
                "endpoint": m["endpoint"],
                "strategy": m.get("strategy", ""),
                "source": "in-memory",
            })

    # Validators
    agents.append({
        "agent_id": "railway-validator",
        "role": "validator",
        "endpoint": "https://agent-verification-network-production.up.railway.app",
        "source": "infrastructure",
    })
    agents.append({
        "agent_id": "eigen-validator",
        "role": "validator",
        "endpoint": "http://34.142.184.34:8000",
        "tee": "Intel TDX",
        "source": "EigenCompute TEE",
    })

    return {"agents": agents, "total": len(agents)}


@app.get("/erc8004")
async def erc8004_info():
    """Our ERC-8004 identity and reputation on the official registries."""
    identity = _erc8004.verify_agent_identity(OUR_AGENT_ID) if _erc8004.enabled else None
    reputation = _erc8004.get_agent_reputation(OUR_AGENT_ID, "code-verification") if _erc8004.enabled else None
    return {
        "agent_id": OUR_AGENT_ID,
        "identity_registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
        "reputation_registry": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
        "chain": "base-mainnet",
        "identity": identity,
        "reputation": reputation,
        "enabled": _erc8004.enabled,
    }


@app.get("/protocol")
async def protocol_info():
    """Contract addresses and ABIs — everything an agent needs to interact directly."""
    import json as _json
    from pathlib import Path

    contracts = {}
    commerce_path = Path(__file__).parent.parent.parent / "contracts" / "commerce_deployed.json"
    scorer_path = Path(__file__).parent.parent.parent / "contracts" / "deployed.json"

    if commerce_path.exists():
        with open(commerce_path) as f:
            data = _json.load(f)
            contracts["AgenticCommerce"] = {
                "address": data["address"],
                "chain": data.get("chain", "base-mainnet"),
                "explorer": f"https://basescan.org/address/{data['address']}",
                "abi": data["abi"],
                "description": "Job marketplace — create, fund, submit, complete/reject with escrow",
            }

    if scorer_path.exists():
        with open(scorer_path) as f:
            data = _json.load(f)
            contracts["AgentScorer"] = {
                "address": data["address"],
                "chain": data.get("chain", "base-mainnet"),
                "explorer": f"https://basescan.org/address/{data['address']}",
                "abi": data["abi"],
                "description": "On-chain miner reputation scores",
            }

    return {
        "protocol": "Agent Verification Network",
        "network": "base-mainnet",
        "chain_id": 8453,
        "contracts": contracts,
        "identity": {
            "standard": "ERC-8004",
            "registration_tx": "0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751",
        },
        "note": "These contracts are permissionless. Any agent with a wallet can interact directly — no API required.",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Agent Verification Network",
        "version": "1.0.0",
        "mode": get_mode(),
        "commerce_enabled": _commerce.enabled,
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
            "/jobs": "GET — On-chain job status from AgenticCommerce",
            "/protocol": "GET — Contract addresses and ABIs for direct interaction",
            "/pricing": "GET — Verification pricing and x402 config",
            "/skill.md": "GET — Machine-readable skill file for agents",
            "/health": "GET — Health check",
        },
    }
