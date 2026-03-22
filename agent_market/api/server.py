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
import os
import urllib.request
from typing import Optional
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_market.logger import log_event
from agent_market.x402 import check_x402_payment, get_pricing_info, verify_onchain_job
from agent_market.storage import store_on_filecoin
from agent_market.commerce import CommerceClient
from agent_market.registry import RegistryClient
from agent_market.erc8004 import ERC8004Client, OUR_AGENT_ID
from agent_market.token import TokenClient
from agent_market.keys import KeyManager

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

# Protocol credits token (AVNC)
_token = TokenClient()

# On-chain scorer
from agent_market.chain import ChainScorer
_scorer = ChainScorer()

# Lock for serializing on-chain transactions (prevents nonce conflicts)
import threading
_onchain_lock = threading.Lock()

# API key manager
_keys = KeyManager()

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


def _process_onchain_background(task_id: str, response):
    """After verification: record score + create job on-chain. Serialized to prevent nonce conflicts."""
    import hashlib

    def _do():
        with _onchain_lock:  # Serialize all on-chain txs to prevent nonce conflicts
            try:
                import time

                # 1. Record score on AgentScorer
                if _scorer.enabled and response.confidence and response.confidence > 0:
                    score_result = _scorer.record_score(
                        agent_id=response.agent_id or "local",
                        task_id=task_id,
                        score=response.confidence,
                        round_num=0,
                    )
                    if score_result:
                        log_event(
                            event_type="score_recorded",
                            agent_role="validator",
                            agent_id="railway-validator",
                            details={
                                "task_id": task_id,
                                "miner": response.agent_id or "local",
                                "score": response.confidence,
                                "tx_hash": score_result.get("tx_hash"),
                                "chain": score_result.get("chain"),
                            },
                        )
                    time.sleep(2)  # Wait for nonce to update

                # 2. Create job on AgenticCommerceV2
                if _commerce.enabled:
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
                                "chain": job_result["chain"],
                            },
                        )

            except Exception as e:
                logger.warning(f"Background on-chain processing failed: {e}")

    if _commerce.enabled or _scorer.enabled:
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
    code: str = Field(default="", description="Source code to verify (for code-verification tasks)")
    text: str = Field(default="", description="Text to review (for text-review tasks)")
    intent: str = Field(description="What the code/text should do or convey")
    language: str = Field(default="python", description="Programming language (code tasks only)")
    task_type: str = Field(default="code-verification", description="Task type: 'code-verification' or 'text-review'")
    job_id: Optional[int] = Field(default=None, description="Pre-funded job ID on AgenticCommerceV2 (direct payment mode)")


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
    # Payment gate: API key → x402 → job_id → 402
    if raw_request:
        # Path 1: API key (registered clients + internal services)
        request_key = (
            raw_request.headers.get("X-API-Key")
            or raw_request.headers.get("x-api-key")
        )
        if request_key:
            key_info = _keys.validate_key(request_key)
            if key_info and key_info.get("valid"):
                if key_info.get("credits_remaining", 0) > 0:
                    _keys.use_credit(request_key, "/verify")
                    # Proceed with verification
                else:
                    return JSONResponse(status_code=402, content={
                        "error": "Credits exhausted",
                        "message": f"No credits remaining for {key_info.get('agent_name', 'this key')}. Pay with AVNC or x402 to continue.",
                        "credits_remaining": 0,
                    })
            elif not key_info:
                return JSONResponse(status_code=401, content={"error": "Invalid API key"})

        # Path 2: Direct on-chain payment (job_id)
        elif request.job_id is not None:
            valid, msg = verify_onchain_job(request.job_id, _commerce)
            if not valid:
                return JSONResponse(status_code=402, content={"error": "Payment Required", "message": msg})

        # Path 3: x402 payment header
        else:
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
                        "code": request.code or request.text,
                        "text": request.text,
                        "intent": request.intent,
                        "language": request.language,
                        "task_type": request.task_type,
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
            use_llm = os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes")
            if request.task_type == "text-review":
                from agent_market.miner.text_analyzer import analyze_text
                best_result = analyze_text(
                    text=request.text or request.code,
                    intent=request.intent,
                    use_llm=use_llm,
                )
            else:
                from agent_market.miner.analyzer import analyze_code
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
        _process_onchain_background(task_id, response)

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


class CreateJobRequest(BaseModel):
    title: str = Field(description="Short description of the task")
    description: str = Field(description="Detailed description of what needs to be done")
    task_type: str = Field(default="code-verification", description="Task type: code-verification or text-review")
    code: str = Field(default="", description="Code to verify (for code-verification tasks)")
    text: str = Field(default="", description="Text to review (for text-review tasks)")
    intent: str = Field(description="What the code/text should do or convey")
    budget_avnc: float = Field(default=5.0, description="Budget in AVNC tokens")


# In-memory marketplace jobs (links on-chain job IDs to task details)
_marketplace_jobs: dict = {}


@app.post("/jobs/create")
async def create_marketplace_job(request: CreateJobRequest, raw_request: Request = None):
    """
    Create a task on the marketplace. The job is created on-chain via AgenticCommerceV2.
    Miners can browse and claim it.

    Two ways to fund:
    1. Include API key — we fund from the validator's balance (deducts credits)
    2. Fund directly on-chain — call AgenticCommerceV2.createJob() + fund() yourself
    """
    # Check API key for credit-based funding
    request_key = None
    if raw_request:
        request_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key")

    if request_key:
        key_info = _keys.validate_key(request_key)
        if not key_info or not key_info.get("valid"):
            return JSONResponse(status_code=401, content={"error": "Invalid API key"})
        if key_info.get("credits_remaining", 0) <= 0:
            return JSONResponse(status_code=402, content={"error": "No credits remaining"})
        # Use a credit for creating the job
        _keys.use_credit(request_key, "/jobs/create")

    import hashlib
    task_id = str(uuid4())
    desc_hash = hashlib.sha256(f"{request.title}:{task_id}".encode()).digest()

    # Create on-chain job
    job_result = None
    if _commerce.enabled:
        job_result = _commerce.create_job(description_hash=desc_hash)

    # Store marketplace details
    job_data = {
        "task_id": task_id,
        "title": request.title,
        "description": request.description,
        "task_type": request.task_type,
        "code": request.code,
        "text": request.text,
        "intent": request.intent,
        "budget_avnc": request.budget_avnc,
        "status": "open",
        "on_chain_job_id": job_result.get("job_id") if job_result else None,
        "on_chain_tx": job_result.get("tx_hash") if job_result else None,
        "claimed_by": None,
        "result": None,
    }
    _marketplace_jobs[task_id] = job_data

    log_event(
        event_type="marketplace_job_created",
        agent_role="client",
        agent_id=request_key[:12] + "..." if request_key else "anonymous",
        details={
            "task_id": task_id,
            "title": request.title,
            "task_type": request.task_type,
            "budget_avnc": request.budget_avnc,
            "on_chain_job_id": job_data.get("on_chain_job_id"),
        },
    )

    return {
        "success": True,
        "task_id": task_id,
        "title": request.title,
        "task_type": request.task_type,
        "status": "open",
        "on_chain_job_id": job_data.get("on_chain_job_id"),
        "on_chain_tx": job_data.get("on_chain_tx"),
        "message": "Job posted to marketplace. Miners can claim it at /jobs/marketplace.",
    }


@app.get("/jobs/marketplace")
async def get_marketplace_jobs():
    """Browse open marketplace jobs that miners can claim."""
    open_jobs = [
        {
            "task_id": j["task_id"],
            "title": j["title"],
            "task_type": j["task_type"],
            "intent": j["intent"],
            "budget_avnc": j["budget_avnc"],
            "status": j["status"],
            "has_code": bool(j.get("code")),
            "has_text": bool(j.get("text")),
        }
        for j in _marketplace_jobs.values()
        if j["status"] in ("open", "funded")
    ]

    return {
        "jobs": open_jobs,
        "total_open": len(open_jobs),
        "total_all": len(_marketplace_jobs),
    }


@app.post("/jobs/{task_id}/claim")
async def claim_marketplace_job(task_id: str, raw_request: Request = None):
    """
    Miner claims a marketplace job. The miner receives the task details and
    must submit a result via /jobs/{task_id}/submit.
    """
    if task_id not in _marketplace_jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    job = _marketplace_jobs[task_id]
    if job["status"] not in ("open", "funded"):
        return JSONResponse(status_code=400, content={"error": f"Job is {job['status']}, cannot claim"})

    # Get miner identity from API key
    miner_id = "anonymous"
    if raw_request:
        request_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key")
        if request_key:
            key_info = _keys.validate_key(request_key)
            if key_info:
                miner_id = key_info.get("agent_name", "anonymous")

    job["status"] = "claimed"
    job["claimed_by"] = miner_id

    return {
        "success": True,
        "task_id": task_id,
        "title": job["title"],
        "task_type": job["task_type"],
        "intent": job["intent"],
        "code": job.get("code", ""),
        "text": job.get("text", ""),
        "budget_avnc": job["budget_avnc"],
        "message": "Job claimed. Submit your result at POST /jobs/{task_id}/submit",
    }


@app.post("/jobs/{task_id}/submit")
async def submit_marketplace_job(task_id: str, raw_request: Request = None):
    """
    Miner submits result for a claimed marketplace job.
    The validator scores the result and completes/rejects on-chain.
    """
    if task_id not in _marketplace_jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    job = _marketplace_jobs[task_id]
    if job["status"] != "claimed":
        return JSONResponse(status_code=400, content={"error": f"Job is {job['status']}, cannot submit"})

    try:
        body = await raw_request.json() if raw_request else {}
    except Exception:
        body = {}

    # Run the analysis locally if no result provided
    result = body.get("result")
    if not result:
        use_llm = os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes")
        if job["task_type"] == "text-review":
            from agent_market.miner.text_analyzer import analyze_text
            result = analyze_text(text=job.get("text") or job.get("code", ""), intent=job["intent"], use_llm=use_llm)
        else:
            from agent_market.miner.analyzer import analyze_code
            result = analyze_code(code=job.get("code", ""), intent=job["intent"], use_llm=use_llm)

    job["status"] = "completed"
    job["result"] = result

    log_event(
        event_type="marketplace_job_completed",
        agent_role="miner",
        agent_id=job.get("claimed_by", "anonymous"),
        details={
            "task_id": task_id,
            "task_type": job["task_type"],
            "issues_found": len(result.get("issues", [])),
            "confidence": result.get("confidence", 0),
        },
    )

    return {
        "success": True,
        "task_id": task_id,
        "status": "completed",
        "result": result,
    }


@app.get("/jobs/list")
async def list_jobs():
    """List all on-chain jobs with details from AgenticCommerceV2."""
    if not _commerce.enabled:
        return {"jobs": [], "total": 0}

    try:
        count = _commerce.get_job_count()
        states = ["Open", "Funded", "Submitted", "Completed", "Rejected", "Expired"]
        jobs = []

        # Read last 50 jobs (or all if fewer)
        start = max(0, count - 50)
        for i in range(start, count):
            try:
                job = _commerce.contract.functions.getJob(i).call()
                client, provider, evaluator, description, budget, token, state, deliverable, created_at = job

                token_symbol = "AVNC" if token.lower() != "0x0000000000000000000000000000000000000000" else "ETH"
                budget_human = budget / 1e18

                jobs.append({
                    "id": i,
                    "client": client,
                    "provider": provider if provider != "0x0000000000000000000000000000000000000000" else None,
                    "evaluator": evaluator,
                    "budget": budget_human,
                    "token": token_symbol,
                    "state": states[state] if state < len(states) else f"Unknown({state})",
                    "created_at": created_at,
                })
            except Exception:
                pass

        jobs.reverse()  # Most recent first

        return {
            "jobs": jobs,
            "total": count,
            "contract": _commerce.contract.address,
            "chain": "base-mainnet",
        }
    except Exception as e:
        return {"jobs": [], "total": 0, "error": str(e)}


@app.get("/stats")
async def get_stats():
    """On-chain stats from all contracts — the real numbers."""
    # Count miners vs validators from on-chain registry
    onchain = _registry.get_active_miners() if _registry.enabled else []
    miners_count = len([a for a in onchain if "validator" not in a.get("strategy", "").lower()])
    validators_count = len([a for a in onchain if "validator" in a.get("strategy", "").lower()])

    # Read payment stats from CommerceV2
    total_paid = 0
    total_fees = 0
    if _commerce.enabled:
        try:
            total_paid = _commerce.contract.functions.totalPaidOut().call()
            total_fees = _commerce.contract.functions.totalFees().call()
        except Exception:
            pass

    return {
        "miners_onchain": miners_count,
        "validators": validators_count,
        "jobs_onchain": _commerce.get_job_count() if _commerce.enabled else 0,
        "verifications": len(results),
        "total_paid_wei": total_paid,
        "total_fees_wei": total_fees,
        "total_volume_wei": total_paid + total_fees,
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

    # On-chain agents from MinerRegistry (miners + validators)
    onchain_agents = _registry.get_active_miners() if _registry.enabled else []
    for m in onchain_agents:
        strategy = m.get("strategy", "")
        is_validator = "validator" in strategy.lower()
        agents.append({
            "agent_id": m["agent_id"],
            "role": "validator" if is_validator else "miner",
            "endpoint": m["endpoint"],
            "strategy": strategy,
            "owner": m.get("owner", ""),
            "registered_at": m.get("registered_at", 0),
            "tee": "Intel TDX" if "tee" in strategy.lower() else None,
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

    return {"agents": agents, "total": len(agents)}


_register_rate_limit: dict = {}  # IP → timestamp

@app.post("/register")
async def register_client(request: Request):
    """
    Register as a client and get an API key.

    Send your agent name (unique) and optionally a wallet address.
    You get 10 free verifications. After that, pay with AVNC or x402.
    Rate limited: 1 registration per IP per hour.
    """
    import time as _time

    # Rate limit by IP
    client_ip = request.client.host if request.client else "unknown"
    last_register = _register_rate_limit.get(client_ip, 0)
    if _time.time() - last_register < 3600:  # 1 hour
        return JSONResponse(status_code=429, content={
            "error": "Rate limited",
            "message": "One registration per hour. Try again later.",
        })

    try:
        body = await request.json()
        agent_name = body.get("agent_name") or body.get("name")
        wallet_address = body.get("wallet_address") or body.get("address")

        if not agent_name:
            return JSONResponse(status_code=400, content={
                "error": "Missing agent_name",
                "hint": "Send {\"agent_name\": \"my-agent\"} to register",
            })

        # Check if name is already taken
        if _keys.is_name_taken(agent_name):
            return JSONResponse(status_code=409, content={
                "error": f"Agent name '{agent_name}' is already registered",
                "hint": "Choose a different name",
            })

        result = _keys.create_key(agent_name=agent_name, wallet_address=wallet_address)
        if result:
            _register_rate_limit[client_ip] = _time.time()
            log_event(
                event_type="client_registered",
                agent_role="client",
                agent_id=agent_name,
                details={"key_prefix": result["key_prefix"], "credits": result["credits"]},
            )
            return {
                "success": True,
                **result,
                "usage": "Include your key as: -H 'X-API-Key: your-key-here'",
                "endpoints": {
                    "/verify": "Submit code for verification (costs 1 credit per call)",
                    "/token": "AVNC token info",
                    "/faucet": "Claim free AVNC tokens (requires wallet address)",
                    "/pricing": "Payment options when credits run out",
                },
            }
        return JSONResponse(status_code=500, content={"error": "Registration failed"})

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/keys/stats")
async def key_stats():
    """API key usage statistics for this validator."""
    return _keys.get_stats()


@app.get("/token")
async def token_info():
    """Protocol credits (AVNC) token info."""
    return _token.get_info()


@app.post("/faucet")
async def claim_faucet(request: Request):
    """Claim free AVNC credits. Send your wallet address to receive 20 credits."""
    try:
        body = await request.json()
        address = body.get("address")
        if not address:
            return JSONResponse(status_code=400, content={"error": "Missing address field"})

        result = _token.claim_faucet(address)
        if result:
            log_event(
                event_type="faucet_claim",
                agent_role="system",
                agent_id="faucet",
                details=result,
            )
            return {"success": True, **result}
        else:
            return JSONResponse(status_code=500, content={"error": "Faucet claim failed. Token may not be enabled."})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


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
    base = Path(__file__).parent.parent.parent / "contracts"

    contract_files = {
        "AgenticCommerceV2": ("commerce_v2_deployed.json", "Job marketplace (ERC-8183) — escrow + 85/15 fee split. This is the active version."),
        "MinerRegistry": ("registry_deployed.json", "On-chain agent discovery — miners and validators register permanently."),
        "AgentScorer": ("deployed.json", "On-chain miner quality scores per task."),
        "ProtocolCredits": ("token_deployed.json", "AVNC token (ERC-20) — protocol credits with faucet. Agents use AVNC to pay for tasks."),
        "AgenticCommerce": ("commerce_deployed.json", "Job marketplace V1 (legacy, no fee split)."),
    }

    for name, (filename, description) in contract_files.items():
        path = base / filename
        if path.exists():
            with open(path) as f:
                data = _json.load(f)
                contracts[name] = {
                    "address": data["address"],
                    "chain": data.get("chain", "base-mainnet"),
                    "explorer": f"https://basescan.org/address/{data['address']}",
                    "abi": data["abi"],
                    "description": description,
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
