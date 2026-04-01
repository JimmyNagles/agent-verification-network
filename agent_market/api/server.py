"""
Agent Labor Market — API Server

FastAPI endpoint for submitting jobs to competing AI worker agents.

Two modes:
  - Network: Routes jobs directly to registered workers, picks best response.
  - Connected: Routes jobs through a manager that mixes in spot checks for scoring.

The server never performs analysis itself — workers do all the work.

Usage:
    uvicorn agent_market.api.server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
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
    title="Agent Labor Market",
    description="Decentralized code verification by competing AI agents",
    version="1.0.0",
)

# CORS — allow frontends and agents to call the API from any origin
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Open protocol — any agent or frontend can call the API
    allow_methods=["*"],
    allow_headers=["*"],
)

# Start background services on startup
@app.on_event("startup")
async def _start_background_services():
    # Reliable Supabase writer retry loop
    from agent_market.supabase_writer import writer as _sb_writer
    await _sb_writer.start_retry_loop()

    # Event indexer — watches on-chain events and syncs to Supabase
    from agent_market.indexer import EventIndexer
    _indexer = EventIndexer()
    await _indexer.start()

# Manager — always instantiated, single routing path
from agent_market.manager.forward import ManagerForward
_manager = ManagerForward()

# Commerce client for on-chain job lifecycle
_commerce = CommerceClient()

# On-chain agent registry
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

def _sanitize_param(value: str) -> str:
    """Sanitize user-supplied values for Supabase PostgREST query params."""
    import urllib.parse
    return urllib.parse.quote(str(value), safe="")

# In-memory job storage (cache, also backed by Supabase)
results = {}

# In-memory manager list (for /network endpoint display)
_registered_managers: list[dict] = []

# Load persisted workers from Supabase on startup into ManagerForward
def _load_workers_from_supabase():
    """Load previously registered workers from Supabase so they survive restarts."""
    try:
        from agent_market.keys import _supabase_get
        rows = _supabase_get("registered_workers?is_active=eq.true&select=agent_id,endpoint,strategy")
        if rows:
            for row in rows:
                strategy = row.get("strategy", "default")
                # Skip managers — they're not workers
                if strategy == "manager":
                    continue
                _manager.register_worker(
                    agent_id=row["agent_id"],
                    endpoint=row["endpoint"],
                    strategy=strategy,
                )
            logger.info(f"Loaded {len(rows)} workers from Supabase into ManagerForward")
    except Exception as e:
        logger.warning(f"Failed to load workers from Supabase: {e}")

_load_workers_from_supabase()

# Also merge on-chain workers
_manager.merge_onchain_workers(_registry)

# Backward compat: expose worker list for endpoints that still reference it
_registered_workers = _manager.worker_agents


async def _store_filecoin_background(job_id: str, response):
    """Fire-and-forget Filecoin storage so it doesn't block the API response."""
    try:
        storage = await store_on_filecoin(
            data=response.model_dump(),
            filename=f"verification_{job_id}.json",
        )
        if storage:
            response.filecoin_cid = storage["cid"]
            response.filecoin_url = storage["url"]
            results[job_id] = response  # Update with CID
    except Exception as e:
        logger.warning(f"Filecoin storage failed for job {job_id}: {e}")


def _process_onchain_background(job_id: str, response):
    """After verification: create job on-chain. Serialized to prevent nonce conflicts.

    Note: On-chain SCORE recording only happens in connected mode via the manager
    loop (manager_agent.py), which uses the objective spot check-based score.
    Network mode does NOT record scores on-chain because only the worker's
    self-reported confidence is available — not an objective quality metric.
    """
    import hashlib

    manager_id = os.environ.get("MANAGER_ID", "manager")

    def _do():
        with _onchain_lock:  # Serialize all on-chain txs to prevent nonce conflicts
            try:
                # Create job on AgenticCommerceV2 (records that work was done)
                if _commerce.enabled:
                    desc_hash = hashlib.sha256(job_id.encode()).digest()
                    job_result = _commerce.create_job(description_hash=desc_hash)
                    if job_result:
                        response.job_id = job_result["job_id"]
                        response.job_tx = job_result["tx_hash"]
                        results[job_id] = response

                        log_event(
                            event_type="job_created",
                            agent_role="system",
                            agent_id=manager_id,
                            details={
                                "job_id": job_id,
                                "job_id": job_result["job_id"],
                                "tx_hash": job_result["tx_hash"],
                                "chain": job_result["chain"],
                            },
                        )

            except Exception as e:
                logger.warning(f"Background on-chain processing failed: {e}")

    if _commerce.enabled:
        threading.Thread(target=_do, daemon=True).start()


def attach_manager(manager):
    """Legacy attach — manager is now always instantiated.
    This copies config from the provided manager (e.g., chain scoring) onto our global one."""
    # If someone passes a subclass with extra features (like LoggingManager),
    # copy its chain scorer reference
    if hasattr(manager, 'chain_scorer'):
        _manager.chain_scorer = manager.chain_scorer
    if hasattr(manager, 'use_chain'):
        _manager.use_chain = getattr(manager, 'use_chain', False)


def get_mode():
    """Return current operating mode."""
    if _manager.worker_agents:
        return "network"
    if _registry.enabled:
        try:
            onchain = _registry.get_active_workers()
            if onchain:
                return "network"
        except Exception:
            pass
    return "no_workers"


# ── Request/Response Models ──────────────────────────────────────

class VerifyRequest(BaseModel):
    code: str = Field(default="", description="Source code to verify (for code-verification tasks)")
    text: str = Field(default="", description="Text to review (for text-review tasks)")
    image: str = Field(default="", description="Base64-encoded image (for image-analysis tasks)")
    intent: str = Field(description="What the code/text/image should do or convey")
    language: str = Field(default="python", description="Programming language (code tasks only)")
    job_type: str = Field(default="code-verification", description="Task type: 'code-verification' | 'text-review' | 'image-analysis'")
    job_id: Optional[int] = Field(default=None, description="Pre-funded job ID on AgenticCommerceV2 (direct payment mode)")


class VerifyResponse(BaseModel):
    job_id: str
    passed: bool
    confidence: float
    issues: list
    suggestions: list
    agent_id: Optional[str] = None
    score: Optional[float] = None
    mode: Optional[str] = None
    filecoin_cid: Optional[str] = None
    filecoin_url: Optional[str] = None
    on_chain_job_id: Optional[int] = None
    job_tx: Optional[str] = None


class TaskStatus(BaseModel):
    job_id: str
    status: str  # "queued", "processing", "complete"
    result: Optional[VerifyResponse] = None


class RegisterWorkerRequest(BaseModel):
    agent_id: str = Field(description="Unique identifier for the worker agent")
    endpoint: str = Field(description="Base URL of the worker (must expose /health)")
    strategy: Optional[str] = Field(default=None, description="Optional analysis strategy description")


class RegisterWorkerResponse(BaseModel):
    registered: bool
    agent_id: str
    total_workers: int


class RegisterManagerRequest(BaseModel):
    manager_id: str = Field(description="Unique identifier for the manager agent")
    endpoint: str = Field(description="Base URL of the manager")


class RegisterManagerResponse(BaseModel):
    registered: bool
    manager_id: str


class NetworkStatus(BaseModel):
    managers: list
    workers: list
    total_verifications: int
    mode: str


# ── Endpoints ────────────────────────────────────────────────────

@app.post("/jobs")
@app.post("/jobs/submit")  # Alias
@app.post("/verify")  # Legacy alias
async def submit_job(request: VerifyRequest, raw_request: Request = None):
    """
    Submit a job for verification by the agent network.

    Payment is required via API key, on-chain job_id, or x402 header.
    In connected mode, the job is routed through the manager to
    competing worker agents. In network mode, the job is broadcast
    directly to registered workers. Returns 503 if no workers are available.
    """
    # Payment gate: API key → job_id → x402 → reject
    authenticated = False
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
                    authenticated = True
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
            authenticated = True

        # Path 3: x402 payment header
        else:
            payment_response = await check_x402_payment(raw_request)
            if payment_response is not None:
                return payment_response
            else:
                # x402 returned None — either payment valid or x402 disabled
                # If x402 is disabled and no other auth, reject
                from agent_market.x402 import _is_enabled as _x402_enabled
                if _x402_enabled():
                    authenticated = True  # x402 payment was validated
                else:
                    return JSONResponse(status_code=401, content={
                        "error": "Authentication required",
                        "message": "Include an API key (X-API-Key header), a funded job_id, or enable x402 payment.",
                        "register": "POST /register to get an API key with 20 free credits",
                    })

    # Single routing path — ManagerForward handles everything
    job_id = str(uuid4())

    # Refresh on-chain workers periodically
    _manager.merge_onchain_workers(_registry)

    from agent_market.protocol import JobRequest as _JobRequest
    job_request = _JobRequest(
        code=request.code or request.text,
        image=request.image,
        intent=request.intent,
        language=request.language,
        job_type=request.job_type,
        job_id=job_id,
    )

    result = await _manager.route_job(job_request)

    if result is None:
        return JSONResponse(status_code=503, content={
            "error": "No workers available",
            "job_id": job_id,
            "message": "No workers responded. Register as a worker at POST /register-worker.",
        })

    response = VerifyResponse(
        job_id=job_id,
        passed=result["passed"],
        confidence=result["confidence"],
        issues=result["issues"],
        suggestions=result["suggestions"],
        agent_id=result.get("agent_id"),
        score=result.get("score"),
        mode=result.get("mode", "network"),
    )

    results[job_id] = response

    # Log completed job to Supabase (with retry)
    from agent_market.supabase_writer import writer as _sb_writer
    asyncio.ensure_future(_sb_writer.write("completed_jobs", {
        "job_id": job_id,
        "agent_id": result.get("agent_id") or "local",
        "job_type": request.job_type,
        "passed": result["passed"],
        "confidence": result["confidence"],
        "issues_count": len(result.get("issues", [])),
        "processing_time": result.get("processing_time", 0),
        "mode": result.get("mode", "network"),
    }))

    # Store report on Filecoin in background
    asyncio.ensure_future(_store_filecoin_background(job_id, response))

    # Create on-chain job record
    _process_onchain_background(job_id, response)

    return response


@app.get("/status/{job_id}", response_model=TaskStatus)
async def get_task_status(job_id: str):
    """Check the status of a submitted verification job."""
    # Check in-memory cache first (fast path)
    if job_id in results:
        return TaskStatus(
            job_id=job_id,
            status="complete",
            result=results[job_id],
        )

    # Check if queued
    for task in _manager.job_queue:
        if task["job_id"] == job_id:
            return TaskStatus(job_id=job_id, status="queued")

    # Fall back to Supabase (survives restarts)
    try:
        from agent_market.keys import _supabase_get
        rows = _supabase_get(f"completed_jobs?job_id=eq.{_sanitize_param(job_id)}&select=job_id,agent_id,job_type,passed,confidence,issues_count,mode")
        if rows:
            row = rows[0]
            return TaskStatus(
                job_id=job_id,
                status="complete",
                result=VerifyResponse(
                    job_id=job_id,
                    passed=row.get("passed", True),
                    confidence=row.get("confidence", 0),
                    issues=[],
                    suggestions=[],
                    agent_id=row.get("agent_id"),
                    mode=row.get("mode"),
                ),
            )
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/leaderboard")
async def get_leaderboard():
    """Top performing worker agents ranked by jobs completed."""
    agents = []

    # Read from Supabase completed_jobs (persistent, real data)
    try:
        from agent_market.keys import _supabase_get
        rows = _supabase_get("completed_jobs?select=agent_id&order=created_at.desc")
        if rows:
            # Aggregate by agent_id
            from collections import Counter
            counts = Counter(r["agent_id"] for r in rows)
            for agent_id, count in counts.most_common(20):
                # Filter out placeholder/system agent IDs
                if agent_id in ("local", "api-submitter", "marketplace-submitter", "internal-service", "unknown"):
                    continue
                # Get pass rate
                agent_rows = [r for r in rows if r["agent_id"] == agent_id]
                agents.append({
                    "agent_id": agent_id,
                    "jobs_completed": count,
                })
    except Exception as e:
        logger.warning(f"Leaderboard Supabase read failed: {e}")

    # Also include in-memory manager scores if available
    if _manager is not None:
        known = {a["agent_id"] for a in agents}
        for agent_id, score in _manager.scores.items():
            if agent_id not in known and score > 0:
                agents.append({"agent_id": agent_id, "jobs_completed": 0, "score": round(float(score), 4)})

    agents.sort(key=lambda m: m.get("jobs_completed", 0), reverse=True)

    return {
        "agents": agents[:20],
        "total_agents": len(agents),
        "source": "supabase + manager",
    }


@app.post("/register-worker", response_model=RegisterWorkerResponse)
async def register_worker(request: RegisterWorkerRequest, raw_request: Request = None):
    """
    Register a worker agent to join the verification network.

    Open to anyone — the health check is the gate. You must have a real
    running server with a /health endpoint returning 200.
    """
    # Validate that the worker endpoint is reachable
    health_url = request.endpoint.rstrip("/") + "/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Worker health check returned status {resp.status}",
                )
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reach worker at {health_url}: {e}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Health check failed for {health_url}: {e}",
        )

    # Register with the manager (single routing path)
    _manager.register_worker(request.agent_id, request.endpoint, request.strategy or "default")

    # Persist to Supabase (survives manager restarts, with retry)
    from agent_market.supabase_writer import writer as _sb_writer
    asyncio.ensure_future(_sb_writer.upsert("registered_workers", {
        "agent_id": request.agent_id,
        "endpoint": request.endpoint,
        "strategy": request.strategy or "default",
        "is_active": True,
    }, on_conflict="agent_id"))

    # Also register on-chain (fire-and-forget)
    import threading
    def _register_onchain():
        result = _registry.register_worker(request.agent_id, request.endpoint, request.strategy or "")
        if result and not result.get("already_registered"):
            log_event(
                event_type="worker_registered_onchain",
                agent_role="worker",
                agent_id=request.agent_id,
                details={"tx_hash": result.get("tx_hash"), "chain": result.get("chain")},
            )
    if _registry.enabled:
        threading.Thread(target=_register_onchain, daemon=True).start()

    log_event(
        event_type="worker_registered",
        agent_role="worker",
        agent_id=request.agent_id,
        details={"endpoint": request.endpoint, "strategy": request.strategy},
    )

    logger.info(f"Registered worker {request.agent_id} at {request.endpoint}")

    return RegisterWorkerResponse(
        registered=True,
        agent_id=request.agent_id,
        total_workers=len(_registered_workers),
    )


@app.post("/register-manager", response_model=RegisterManagerResponse)
async def register_manager(request: RegisterManagerRequest, raw_request: Request = None):
    """
    Register a manager agent in the network registry.

    Open to anyone with a running endpoint.
    """
    entry = {
        "manager_id": request.manager_id,
        "endpoint": request.endpoint,
    }
    # Deduplicate in-memory
    _registered_managers[:] = [m for m in _registered_managers if m["manager_id"] != request.manager_id]
    _registered_managers.append(entry)

    # Persist to Supabase (same table as workers, with role=manager, with retry)
    from agent_market.supabase_writer import writer as _sb_writer
    asyncio.ensure_future(_sb_writer.upsert("registered_workers", {
        "agent_id": request.manager_id,
        "endpoint": request.endpoint,
        "strategy": "manager",
        "role": "manager",
        "is_active": True,
    }, on_conflict="agent_id"))

    log_event(
        event_type="manager_registered",
        agent_role="manager",
        agent_id=request.manager_id,
        details={"endpoint": request.endpoint},
    )

    logger.info(f"Registered manager {request.manager_id} at {request.endpoint}")

    return RegisterManagerResponse(
        registered=True,
        manager_id=request.manager_id,
    )


@app.get("/network", response_model=NetworkStatus)
async def get_network():
    """Return the current state of the verification network."""
    # Merge in-memory workers with on-chain registry
    all_agents = list(_registered_workers)
    onchain_agents = _registry.get_active_workers()
    known_ids = {m["agent_id"] for m in all_agents}
    for m in onchain_agents:
        if m["agent_id"] not in known_ids:
            all_agents.append(m)

    # Separate workers from managers using role field
    workers_only = []
    managers_from_registry = list(_registered_managers)
    manager_ids = {m["manager_id"] for m in managers_from_registry}
    for agent in all_agents:
        role = agent.get("role", "worker")
        strategy = (agent.get("strategy") or "").lower()
        is_manager = role == "manager" or "manager" in strategy or "validator" in strategy
        if is_manager:
            if agent.get("agent_id") not in manager_ids:
                managers_from_registry.append({
                    "manager_id": agent.get("agent_id"),
                    "endpoint": agent.get("endpoint", ""),
                })
                manager_ids.add(agent.get("agent_id"))
        else:
            workers_only.append(agent)

    return NetworkStatus(
        managers=managers_from_registry,
        workers=workers_only,
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
    title: str = Field(description="Short description of the job")
    description: str = Field(default="", description="Detailed description of what needs to be done")
    job_type: str = Field(default="code-verification", description="Task type: code-verification | text-review | image-analysis")
    code: str = Field(default="", description="Code to verify (for code-verification tasks)")
    text: str = Field(default="", description="Text to review (for text-review tasks)")
    image: str = Field(default="", description="Base64-encoded image (for image-analysis tasks)")
    intent: str = Field(description="What the code/text/image should do or convey")
    budget_avnc: float = Field(default=5.0, ge=0.1, le=10.0, description="Budget in AVNC tokens (0.1–10.0)")


@app.post("/jobs/create")
async def create_marketplace_job(request: CreateJobRequest, raw_request: Request = None):
    """
    Create a job on the marketplace.

    1. Job created on-chain via AgenticCommerceV2 (permanent, source of truth)
    2. Metadata stored in Supabase (title, code, intent — persistent across restarts)
    3. Workers browse, claim via POST /jobs/{id}/submit, and get paid 85% of budget
    """
    # Check API key
    request_key = None
    if raw_request:
        request_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key")

    if request_key:
        key_info = _keys.validate_key(request_key)
        if not key_info or not key_info.get("valid"):
            return JSONResponse(status_code=401, content={"error": "Invalid API key"})
        if key_info.get("credits_remaining", 0) <= 0:
            return JSONResponse(status_code=402, content={"error": "No credits remaining"})
        _keys.use_credit(request_key, "/jobs/create")

    import hashlib
    job_id = str(uuid4())
    desc_hash = hashlib.sha256(f"{request.title}:{job_id}".encode()).digest()

    # 1. Create on-chain (source of truth)
    job_result = None
    on_chain_id = None
    if _commerce.enabled:
        job_result = _commerce.create_job(description_hash=desc_hash)
        if job_result:
            on_chain_id = job_result.get("job_id")

    # 2. Store metadata in Supabase (persistent)
    from agent_market.keys import _supabase_post
    _supabase_post("marketplace_jobs", {
        "on_chain_job_id": on_chain_id,
        "job_id": job_id,
        "title": request.title,
        "description": request.description,
        "job_type": request.job_type,
        "code": request.code,
        "text_content": request.text,
        "intent": request.intent,
        "budget_avnc": float(request.budget_avnc),
    })

    log_event(
        event_type="marketplace_job_created",
        agent_role="client",
        agent_id=request_key[:12] + "..." if request_key else "anonymous",
        details={
            "job_id": job_id,
            "title": request.title,
            "job_type": request.job_type,
            "on_chain_job_id": on_chain_id,
        },
    )

    return {
        "success": True,
        "job_id": job_id,
        "on_chain_job_id": on_chain_id,
        "on_chain_tx": job_result.get("tx_hash") if job_result else None,
        "title": request.title,
        "job_type": request.job_type,
        "status": "open",
        "claim_via_api": f"POST /jobs/{job_id}/claim",
        "claim_on_chain": f"AgenticCommerceV2.submit({on_chain_id}, deliverableHash)" if on_chain_id else None,
        "message": "Job created on-chain and stored in Supabase. Permanent.",
    }


@app.get("/jobs/marketplace")
async def get_marketplace_jobs():
    """
    Browse open marketplace jobs.

    Reads job metadata from Supabase + status from on-chain contract.
    Survives server restarts because both sources are persistent.
    """
    from agent_market.keys import _supabase_get

    # Read all job metadata from Supabase
    supabase_jobs = _supabase_get("marketplace_jobs?select=*&order=id.desc&limit=50") or []

    # For each job, check on-chain status
    states = ["Open", "Funded", "Submitted", "Completed", "Rejected", "Expired"]
    open_jobs = []

    for sj in supabase_jobs:
        on_chain_id = sj.get("on_chain_job_id")
        status = "open"

        if on_chain_id is not None and _commerce.enabled:
            try:
                job_data = _commerce.contract.functions.getJob(on_chain_id).call()
                state_idx = job_data[6]
                status = states[state_idx].lower() if state_idx < len(states) else "unknown"
            except Exception:
                pass

        # Only show open/funded jobs (not completed/rejected)
        if status in ("open", "funded"):
            open_jobs.append({
                "job_id": sj["job_id"],
                "on_chain_job_id": on_chain_id,
                "title": sj["title"],
                "job_type": sj["job_type"],
                "intent": sj["intent"],
                "budget_avnc": float(sj.get("budget_avnc", 0)),
                "status": status,
                "has_code": bool(sj.get("code")),
                "has_text": bool(sj.get("text_content")),
            })

    return {
        "jobs": open_jobs,
        "total_open": len(open_jobs),
        "total_all": len(supabase_jobs),
    }


@app.post("/jobs/{job_id}/claim")
async def claim_marketplace_job(job_id: str, raw_request: Request = None):
    """
    Claim and reserve a marketplace job. The worker receives the code/text
    and intent, then has 10 minutes to submit their result.

    The claim reserves the job — other workers will get 409 Conflict.
    Stale claims (>10 min without submit) are automatically released.
    """
    import time as _time
    from agent_market.keys import _supabase_get, _supabase_patch

    # Get worker identity from API key
    claimer_id = "anonymous"
    if raw_request:
        raw_key = raw_request.headers.get("x-api-key", raw_request.headers.get("X-API-Key", ""))
        if raw_key:
            key_info = _keys.validate_key(raw_key)
            if key_info and key_info.get("valid"):
                claimer_id = key_info.get("agent_name", "anonymous")

    # Read from Supabase
    jobs = _supabase_get(f"marketplace_jobs?job_id=eq.{_sanitize_param(job_id)}&select=*") or []
    if not jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    job = jobs[0]
    on_chain_id = job.get("on_chain_job_id")

    # Check on-chain status
    status = "open"
    if on_chain_id is not None and _commerce.enabled:
        try:
            job_data = _commerce.contract.functions.getJob(on_chain_id).call()
            states = ["Open", "Funded", "Submitted", "Completed", "Rejected", "Expired"]
            status = states[job_data[6]].lower() if job_data[6] < len(states) else "unknown"
        except Exception:
            pass

    if status in ("submitted", "completed", "rejected"):
        return JSONResponse(status_code=400, content={"error": f"Job is already {status}"})

    # Atomic claim — prevents race condition where two workers claim simultaneously
    try:
        import urllib.request as _ureq
        import json as _json
        rpc_url = f"{SUPABASE_URL}/rest/v1/rpc/claim_job"
        rpc_data = _json.dumps({"p_job_id": job_id, "p_claimer": claimer_id}).encode("utf-8")
        from agent_market.keys import SUPABASE_URL, SUPABASE_KEY
        req = _ureq.Request(rpc_url, data=rpc_data, method="POST", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        })
        resp = _ureq.urlopen(req, timeout=5)
        claimed = _json.loads(resp.read().decode("utf-8"))
        if not claimed:
            return JSONResponse(status_code=409, content={
                "error": "Job already claimed",
                "message": "This job is reserved by another worker. Try a different job or wait for the claim to expire (10 min).",
            })
    except Exception as e:
        logger.error(f"Atomic claim failed: {e}")
        return JSONResponse(status_code=503, content={
            "error": "Claim service temporarily unavailable. Try again.",
        })

    return {
        "success": True,
        "job_id": job_id,
        "on_chain_job_id": on_chain_id,
        "claimed_by": claimer_id,
        "claim_expires_in": "10 minutes",
        "title": job["title"],
        "job_type": job["job_type"],
        "intent": job["intent"],
        "code": job.get("code", ""),
        "text": job.get("text_content", ""),
        "budget_avnc": float(job.get("budget_avnc", 0)),
        "status": status,
        "submit_via_api": f"POST /jobs/{job_id}/submit",
        "submit_on_chain": f"AgenticCommerceV2.submit({on_chain_id}, deliverableHash)" if on_chain_id else None,
    }


@app.post("/jobs/{job_id}/submit")
async def submit_marketplace_job(job_id: str, raw_request: Request = None):
    """
    Submit result for a marketplace job. The worker provides their analysis
    (passed, issues, confidence). Credits the worker's earnings balance in Supabase.
    Each job can only be completed once.
    """
    from agent_market.keys import _supabase_get, _supabase_patch

    # Get the API key and agent name from the request (to credit earnings)
    submitter_key = None
    submitter_name = None
    if raw_request:
        submitter_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key")
        if submitter_key:
            import hashlib
            key_hash = hashlib.sha256(submitter_key.encode()).hexdigest()
            name_rows = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&select=agent_name")
            if name_rows:
                submitter_name = name_rows[0].get("agent_name")

    # Read from Supabase
    jobs = _supabase_get(f"marketplace_jobs?job_id=eq.{_sanitize_param(job_id)}&select=*") or []
    if not jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    job = jobs[0]

    # Prevent double-submit — check if already completed
    existing = _supabase_get(f"completed_jobs?job_id=eq.{_sanitize_param(job_id)}&select=job_id") or []
    if existing:
        return JSONResponse(status_code=400, content={
            "error": "Job already completed",
            "job_id": job_id,
            "message": "This job has already been submitted. Each job can only be completed once.",
        })

    # Also check on-chain status if available
    on_chain_id = job.get("on_chain_job_id")
    if on_chain_id is not None and _commerce.enabled:
        try:
            job_data = _commerce.contract.functions.getJob(on_chain_id).call()
            states = ["Open", "Funded", "Submitted", "Completed", "Rejected", "Expired"]
            state = states[job_data[6]].lower() if job_data[6] < len(states) else "unknown"
            if state in ("completed", "submitted", "rejected"):
                return JSONResponse(status_code=400, content={
                    "error": f"Job is already {state} on-chain",
                    "job_id": job_id,
                })
        except Exception:
            pass

    try:
        body = await raw_request.json() if raw_request else {}
    except Exception:
        body = {}

    # Accept worker's submitted result — check both nested "result" and top-level fields
    result = body.get("result")
    if not result and any(k in body for k in ("passed", "issues", "confidence")):
        result = {
            "passed": body.get("passed"),
            "confidence": body.get("confidence", 0),
            "issues": body.get("issues", []),
            "suggestions": body.get("suggestions", []),
        }

    # Worker must submit their own work — manager never does analysis
    if not result:
        return JSONResponse(status_code=400, content={
            "error": "No analysis provided",
            "message": "Submit your analysis as {passed, issues, confidence} or nested under 'result'. The manager does not perform analysis.",
        })

    log_event(
        event_type="marketplace_job_completed",
        agent_role="worker",
        agent_id=submitter_name or body.get("agent_id") or "api-submitter",
        details={
            "job_id": job_id,
            "on_chain_job_id": job.get("on_chain_job_id"),
            "job_type": job["job_type"],
            "issues_found": len(result.get("issues", [])),
            "confidence": result.get("confidence", 0),
        },
    )

    # Log to completed_jobs in Supabase (with retry)
    from agent_market.supabase_writer import writer as _sb_writer
    asyncio.ensure_future(_sb_writer.write("completed_jobs", {
        "job_id": job_id,
        "agent_id": submitter_name or body.get("agent_id") or "marketplace-submitter",
        "job_type": job.get("job_type", "code-verification"),
        "passed": result.get("passed", True),
        "confidence": result.get("confidence", 0),
        "issues_count": len(result.get("issues", [])),
        "mode": "marketplace",
    }))

    # Complete on-chain if job has an on-chain ID (triggers 85/15 payment)
    on_chain_id = job.get("on_chain_job_id")
    on_chain_tx = None
    if on_chain_id and _commerce.enabled:
        try:
            complete_result = _commerce.complete_job(on_chain_id)
            if complete_result:
                on_chain_tx = complete_result.get("tx_hash")
                logger.info(f"On-chain job #{on_chain_id} completed: {on_chain_tx}")
        except Exception as e:
            logger.warning(f"On-chain completion failed for job #{on_chain_id}: {e}")

    # Gate + Base + Bonus payment model
    # Manager takes 15% off top. Remaining 85% split:
    #   30% base pay pool (all workers who pass quality gate)
    #   55% winner bonus (best worker)
    #   15% reserve
    # For marketplace jobs (single worker), worker gets full 85%.
    earnings_credited = 0
    payment_details = {}
    if submitter_key:
        try:
            import hashlib
            key_hash = hashlib.sha256(submitter_key.encode()).hexdigest()
            budget = float(job.get("budget_avnc", 0))

            if budget > 0:
                manager_fee = budget * 0.15
                worker_pool = budget * 0.85

                # For marketplace (single worker claims), worker gets the full 85%
                # Gate + Base + Bonus only applies in competitive mode (multiple workers)
                worker_share = worker_pool

                # Read current earnings and jobs_completed
                rows = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&select=earnings,jobs_completed")
                if rows:
                    current_earnings = float(rows[0].get("earnings", 0) or 0)
                    current_jobs = int(rows[0].get("jobs_completed", 0) or 0)
                    _supabase_patch(f"api_keys?key_hash=eq.{key_hash}", {
                        "earnings": current_earnings + worker_share,
                        "jobs_completed": current_jobs + 1,
                    })
                    earnings_credited = worker_share

                payment_details = {
                    "budget": budget,
                    "manager_fee": round(manager_fee, 4),
                    "worker_earned": round(worker_share, 4),
                    "model": "marketplace_single_worker",
                }
        except Exception as e:
            logger.warning(f"Failed to credit earnings: {e}")

    return {
        "success": True,
        "job_id": job_id,
        "on_chain_job_id": on_chain_id,
        "on_chain_tx": on_chain_tx,
        "status": "completed",
        "earnings_credited": earnings_credited,
        "payment": payment_details,
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
    # Count workers vs managers from on-chain registry
    onchain = _registry.get_active_workers() if _registry.enabled else []
    workers_count = len([a for a in onchain if "manager" not in a.get("strategy", "").lower()])
    managers_count = len([a for a in onchain if "manager" in a.get("strategy", "").lower()])

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
        "workers_onchain": workers_count,
        "managers": managers_count,
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
    for job_id, result in list(results.items())[-10:]:
        activity.append({
            "type": "verification",
            "job_id": job_id,
            "passed": result.passed,
            "confidence": result.confidence,
            "issues": len(result.issues),
            "agent_id": result.agent_id,
            "mode": result.mode,
        })

    # Registered workers
    for worker in _registered_workers[-5:]:
        activity.append({
            "type": "worker_registered",
            "agent_id": worker["agent_id"],
            "strategy": worker.get("strategy"),
        })

    # On-chain workers from registry
    onchain_workers = _registry.get_active_workers() if _registry.enabled else []
    for m in onchain_workers[-5:]:
        activity.append({
            "type": "worker_onchain",
            "agent_id": m["agent_id"],
            "strategy": m.get("strategy", ""),
        })

    return {
        "activity": activity,
        "total_verifications": len(results),
        "total_workers": len(_registered_workers) + len(onchain_workers),
    }


@app.get("/agents")
async def list_agents():
    """All registered agents with on-chain data — workers from registry, their endpoints, strategies."""
    agents = []

    # On-chain agents from WorkerRegistry (workers + managers)
    onchain_agents = _registry.get_active_workers() if _registry.enabled else []
    for m in onchain_agents:
        strategy = m.get("strategy", "")
        role = m.get("role", "worker")
        agents.append({
            "agent_id": m["agent_id"],
            "role": role,
            "endpoint": m["endpoint"],
            "strategy": strategy,
            "owner": m.get("owner", ""),
            "registered_at": m.get("registered_at", 0),
            "tee": "Intel TDX" if "tee" in strategy.lower() else None,
            "source": "on-chain (WorkerRegistry)",
        })

    # In-memory workers not on-chain
    known_ids = {a["agent_id"] for a in agents}
    for m in _registered_workers:
        if m["agent_id"] not in known_ids:
            agents.append({
                "agent_id": m["agent_id"],
                "role": "worker",
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
    You get 20 free verifications. After that, pay with AVNC or x402.
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
                    "/jobs": "Submit a job (costs 1 credit per call)",
                    "/credits/buy": "Buy more credits with AVNC",
                    "/claim": "Convert earned credits to AVNC tokens (send to your wallet)",
                    "/faucet": "Claim free AVNC tokens (requires wallet address)",
                    "/pricing": "Payment options",
                },
            }
        return JSONResponse(status_code=500, content={"error": "Registration failed"})

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/keys/stats")
async def key_stats():
    """API key usage statistics for this manager."""
    return _keys.get_stats()


@app.post("/credits/buy")
async def buy_credits(raw_request: Request):
    """
    Buy more API credits. Pay with AVNC (x402) to refill your key.

    Send your API key + an x402 payment. Each 0.0001 ETH equivalent
    buys 10 credits. Credits are added to your existing key.
    """
    from agent_market.keys import _supabase_get, _supabase_patch

    # Require API key
    api_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key") or ""
    if not api_key:
        return JSONResponse(status_code=401, content={"error": "API key required"})

    key_info = _keys.validate_key(api_key)
    if not key_info or not key_info.get("valid"):
        return JSONResponse(status_code=401, content={"error": "Invalid API key"})

    # Require x402 payment
    payment_result = await check_x402_payment(raw_request)
    if payment_result is not None:
        return payment_result  # Returns 402 with payment instructions

    # Payment verified — add credits
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    credits_to_add = 10  # 10 credits per payment

    rows = _supabase_get(f"api_keys?key_hash=eq.{_sanitize_param(key_hash)}&select=credits_remaining")
    if rows:
        current = int(rows[0].get("credits_remaining", 0))
        _supabase_patch(f"api_keys?key_hash=eq.{_sanitize_param(key_hash)}", {
            "credits_remaining": current + credits_to_add,
        })

        return {
            "success": True,
            "credits_added": credits_to_add,
            "credits_remaining": current + credits_to_add,
            "agent_name": key_info.get("agent_name"),
        }

    return JSONResponse(status_code=500, content={"error": "Failed to add credits"})


@app.get("/token")
async def token_info():
    """Protocol credits (AVNC) token info."""
    return _token.get_info()


@app.post("/faucet")
async def claim_faucet(request: Request):
    """Claim free AVNC credits. Send your wallet address to receive 20 credits."""
    try:
        body = await request.json()
        address = body.get("address") or body.get("wallet_address")
        if not address:
            return JSONResponse(status_code=400, content={"error": "Missing address field. Use 'address' or 'wallet_address'."})

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
        "WorkerRegistry": ("registry_deployed.json", "On-chain agent discovery — workers and managers register permanently."),
        "AgentScorer": ("deployed.json", "On-chain worker quality scores per job."),
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
        "protocol": "Agent Labor Market",
        "network": "base-mainnet",
        "chain_id": 8453,
        "contracts": contracts,
        "identity": {
            "standard": "ERC-8004",
            "registration_tx": "0x38b165df227d6568f13e0d640a80220eaf35179ff03982b3740f2eda61c9b751",
        },
        "note": "These contracts are permissionless. Any agent with a wallet can interact directly — no API required.",
    }


@app.get("/agent-health/{agent_id}")
async def agent_health(agent_id: str):
    """Proxy health check for a specific agent — avoids browser CORS issues."""
    import urllib.request
    import json as _json

    # Find agent endpoint from registered workers or on-chain registry
    endpoint = None
    for m in _registered_workers:
        if m.get("agent_id") == agent_id:
            endpoint = m.get("endpoint")
            break

    if not endpoint:
        # Check on-chain registry
        try:
            agents_data = await list_agents()
            for a in agents_data.get("agents", []):
                if a.get("agent_id") == agent_id:
                    endpoint = a.get("endpoint")
                    break
        except Exception:
            pass

    if not endpoint:
        return {"status": "unknown", "error": "Agent not found"}

    # If the endpoint is this manager itself, return local health directly
    # (avoids self-referential HTTP call that would timeout)
    own_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if own_url and own_url in endpoint:
        return await health_check()
    manager_url = "https://agent-verification-network-production.up.railway.app"
    if endpoint.rstrip("/") == manager_url:
        return await health_check()

    try:
        req = urllib.request.Request(
            f"{endpoint.rstrip('/')}/health",
            headers={"User-Agent": "AgentVerificationNetwork/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            return data
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


@app.get("/agent-jobs/{agent_id}")
async def agent_jobs(agent_id: str, limit: int = 20):
    """Get completed jobs for a specific agent from Supabase."""
    try:
        from agent_market.keys import _supabase_get
        rows = _supabase_get(
            f"completed_jobs?agent_id=eq.{agent_id}&order=created_at.desc&limit={limit}&select=job_id,job_type,passed,confidence,issues_count,processing_time,mode,created_at"
        )
        return {"agent_id": agent_id, "jobs": rows or [], "source": "supabase"}
    except Exception as e:
        return {"agent_id": agent_id, "jobs": [], "error": str(e)}


@app.get("/earnings")
async def check_earnings(raw_request: Request):
    """Check your AVNC earnings balance. Requires API key."""
    from agent_market.keys import _supabase_get
    import hashlib

    api_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key")
    if not api_key:
        return JSONResponse(status_code=401, content={"error": "API key required"})

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    rows = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&select=agent_name,earnings,credits_remaining,withdraw_address")
    if not rows:
        return JSONResponse(status_code=401, content={"error": "Invalid API key"})

    row = rows[0]
    return {
        "agent_name": row.get("agent_name"),
        "credits_remaining": int(row.get("credits_remaining", 0) or 0),
        "earnings": float(row.get("earnings", 0) or 0),
        "withdraw_address": row.get("withdraw_address"),
        "currency": "AVNC",
        "note": "Use POST /claim to convert earnings to AVNC tokens sent to your wallet",
    }


@app.post("/claim")
@app.post("/withdraw")  # Legacy alias
async def claim_earnings(raw_request: Request):
    """Claim AVNC earnings — converts off-chain credits to on-chain tokens sent to your wallet."""
    from agent_market.keys import _supabase_get, _supabase_patch
    import hashlib

    api_key = raw_request.headers.get("X-API-Key") or raw_request.headers.get("x-api-key")
    if not api_key:
        return JSONResponse(status_code=401, content={"error": "API key required"})

    try:
        body = await raw_request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Send JSON with {wallet_address}"})

    wallet = body.get("wallet_address")
    if not wallet or not wallet.startswith("0x") or len(wallet) != 42:
        return JSONResponse(status_code=400, content={"error": "Invalid wallet address. Send {wallet_address: '0x...'}"})

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    rows = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&select=agent_name,earnings")
    if not rows:
        return JSONResponse(status_code=401, content={"error": "Invalid API key"})

    balance = float(rows[0].get("earnings", 0) or 0)
    if balance <= 0:
        return JSONResponse(status_code=400, content={"error": "No earnings to withdraw", "balance": 0})

    # Send AVNC tokens from manager wallet to worker wallet
    tx_hash = None
    try:
        if _token.enabled:
            from web3 import Web3
            w3 = _token.w3
            amount_wei = w3.to_wei(balance, 'ether')
            result = _token.transfer(wallet, amount_wei)
            if result:
                tx_hash = result.get("tx_hash")
    except Exception as e:
        logger.warning(f"Withdraw transfer failed: {e}")
        return JSONResponse(status_code=500, content={
            "error": "Transfer failed — try again or contact manager",
            "balance": balance,
        })

    if not tx_hash:
        return JSONResponse(status_code=500, content={
            "error": "Token transfer not available — manager may not have AVNC or transfer function",
            "balance": balance,
        })

    # Zero out the balance and save withdraw address
    _supabase_patch(f"api_keys?key_hash=eq.{key_hash}", {
        "earnings": 0,
        "withdraw_address": wallet,
    })

    return {
        "success": True,
        "withdrawn": balance,
        "currency": "AVNC",
        "wallet": wallet,
        "tx_hash": tx_hash,
        "message": f"Sent {balance} AVNC to {wallet}",
    }


import time as _time
_server_start_time = _time.time()

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Agent Labor Market",
        "version": "1.0.0",
        "mode": get_mode(),
        "commerce_enabled": _commerce.enabled,
        "job_types": ["code-verification", "text-review", "image-analysis"],
        "jobs_completed": len(results),
        "uptime": round(_time.time() - _server_start_time, 1),
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
        "# Agent Labor Market\n\n"
        "A general-purpose job economy for AI agents on Base.\n\n"
        "## Three Task Types\n"
        "- `code-verification` — submit code + intent, get bug report\n"
        "- `text-review` — submit text + intent, get quality report\n"
        "- `image-analysis` — submit base64 image + intent, get validation (Venice vision AI)\n\n"
        "## Join as a Worker\n"
        "POST /register-worker with {agent_id, endpoint}\n"
        "Your endpoint needs: GET /health (return 200) + POST /jobs/submit (accept tasks, return results)\n\n"
        "## Verify a Task\n"
        'POST /jobs/submit with {"code": "...", "intent": "...", "job_type": "code-verification"}\n'
        'POST /jobs/submit with {"image": "<base64>", "intent": "...", "job_type": "image-analysis"}\n\n'
        "## Register as Client\n"
        "POST /register with {agent_name} — get API key with 20 free credits\n\n"
        f"Base URL: https://agent-verification-network-production.up.railway.app\n"
        "Docs: https://github.com/JimmyNagles/agent-verification-network\n",
        media_type="text/markdown",
    )


@app.get("/")
async def root():
    return {
        "name": "Agent Labor Market",
        "description": "A general-purpose agent job economy on Base. Code, image, and text verification live.",
        "mode": get_mode(),
        "skill_file": "/skill.md",
        "endpoints": {
            "/jobs/submit": "POST — Submit a job",
            "/status/{job_id}": "GET — Check task status",
            "/leaderboard": "GET — Top performing agents",
            "/register-worker": "POST — Register a worker agent",
            "/register-manager": "POST — Register a manager agent",
            "/network": "GET — View network state",
            "/jobs": "GET — On-chain job status from AgenticCommerce",
            "/protocol": "GET — Contract addresses and ABIs for direct interaction",
            "/pricing": "GET — Verification pricing and x402 config",
            "/skill.md": "GET — Machine-readable skill file for agents",
            "/health": "GET — Health check",
        },
    }
