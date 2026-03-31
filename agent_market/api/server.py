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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Manager reference — None means standalone/demo mode
_manager = None

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

# In-memory job storage
results = {}

# In-memory registries for open network registration
_registered_workers: list[dict] = []
_registered_managers: list[dict] = []
_total_verifications: int = 0

# Load persisted workers from Supabase on startup
def _load_workers_from_supabase():
    """Load previously registered workers from Supabase so they survive restarts."""
    try:
        from agent_market.keys import _supabase_get
        rows = _supabase_get("registered_workers?is_active=eq.true&select=agent_id,endpoint,strategy")
        if rows:
            for row in rows:
                _registered_workers.append({
                    "agent_id": row["agent_id"],
                    "endpoint": row["endpoint"],
                    "strategy": row.get("strategy", "default"),
                })
            logger.info(f"Loaded {len(rows)} workers from Supabase")
    except Exception as e:
        logger.warning(f"Failed to load workers from Supabase: {e}")

_load_workers_from_supabase()


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
                    desc_hash = hashlib.sha256(task_id.encode()).digest()
                    job_result = _commerce.create_job(description_hash=desc_hash)
                    if job_result:
                        response.job_id = job_result["job_id"]
                        response.job_tx = job_result["tx_hash"]
                        results[task_id] = response

                        log_event(
                            event_type="job_created",
                            agent_role="system",
                            agent_id=manager_id,
                            details={
                                "task_id": task_id,
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
    """Attach a manager instance to route jobs through the agent network."""
    global _manager
    _manager = manager


def get_mode():
    """Return current operating mode."""
    if _manager is not None:
        return "connected"
    if _registered_workers:
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
    task_type: str = Field(default="code-verification", description="Task type: 'code-verification' | 'text-review' | 'image-analysis'")
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

@app.post("/jobs/submit")
@app.post("/verify")  # Deprecated alias — use /jobs/submit
async def verify_code(request: VerifyRequest, raw_request: Request = None):
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

    if _manager is not None:
        task_id = _manager.add_task(
            code=request.code,
            intent=request.intent,
            language=request.language,
        )

        result = None
        for _ in range(60):
            result = _manager.get_result(task_id)
            if result is not None:
                break
            await asyncio.sleep(1)

        if result is None:
            return JSONResponse(status_code=503, content={
                "error": "No workers available",
                "task_id": task_id,
                "message": "Task was queued but no workers responded in time. Try again or register as a worker at POST /register-worker.",
            })
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

        # Build combined worker list: in-memory + on-chain registry
        all_workers = list(_registered_workers)
        known_ids = {m["agent_id"] for m in all_workers}

        # Add on-chain workers from WorkerRegistry
        if _registry.enabled:
            try:
                onchain = _registry.get_active_workers()
                for m in onchain:
                    if m["agent_id"] not in known_ids:
                        strategy = m.get("strategy", "")
                        # Skip managers — they're not workers
                        if "manager" in strategy.lower():
                            continue
                        all_workers.append({
                            "agent_id": m["agent_id"],
                            "endpoint": m["endpoint"],
                            "strategy": strategy,
                        })
                        known_ids.add(m["agent_id"])
            except Exception as e:
                logger.warning(f"Failed to read on-chain workers: {e}")

        # Route to workers that support this job type
        if all_workers:
            # Filter workers by job type capability
            job_type = request.task_type or "code-verification"
            eligible_workers = []
            for w in all_workers:
                strategy = (w.get("strategy") or "").lower()
                # Image workers only get image jobs, and image jobs only go to image workers
                is_image_worker = "vision" in strategy or "image" in strategy
                is_image_job = job_type == "image-analysis"
                if is_image_job and not is_image_worker:
                    continue  # Skip non-image workers for image jobs
                if not is_image_job and is_image_worker:
                    continue  # Skip image workers for non-image jobs
                eligible_workers.append(w)

            # Fall back to all workers if no eligible ones found
            if not eligible_workers:
                eligible_workers = all_workers

            worker_responses = []
            for worker in eligible_workers:
                try:
                    data = _json.dumps({
                        "code": request.code or request.text,
                        "text": request.text,
                        "image": request.image,
                        "intent": request.intent,
                        "language": request.language,
                        "task_type": request.task_type,
                        "task_id": task_id,
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"{worker['endpoint'].rstrip('/')}/verify",
                        data=data,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "AgentVerificationNetwork/1.0",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        worker_result = _json.loads(resp.read().decode("utf-8"))
                        worker_responses.append({
                            "agent_id": worker["agent_id"],
                            "result": worker_result,
                        })
                        logger.info(f"Worker {worker['agent_id']} responded: {len(worker_result.get('issues', []))} issues")
                except Exception as e:
                    logger.warning(f"Worker {worker['agent_id']} failed: {e}")

            # Score all responses using the scorer (with consensus if multiple workers)
            if worker_responses:
                from agent_market.manager.scorer import WorkerScorer
                _network_scorer = WorkerScorer()

                # Build response objects for consensus scoring
                all_resp_for_consensus = []
                for wr in worker_responses:
                    class _R:
                        def __init__(self, issues):
                            self.issues = issues
                    all_resp_for_consensus.append(_R(wr["result"].get("issues", [])))

                best_score = -1
                best_result = None
                best_agent = None
                for wr in worker_responses:
                    r = wr["result"]
                    score = _network_scorer.score(
                        response_issues=r.get("issues", []),
                        response_passed=r.get("passed", True),
                        response_confidence=r.get("confidence", 0),
                        response_time=r.get("processing_time", 1.0),
                        is_spot_check=False,
                        known_bugs=None,
                        all_responses=all_resp_for_consensus if len(worker_responses) > 1 else None,
                    )
                    if score > best_score:
                        best_score = score
                        best_result = r
                        best_agent = wr["agent_id"]

                mode = "network"
                logger.info(f"Best response from {best_agent} (score: {best_score:.3f}, confidence: {best_result.get('confidence')})")

        # No workers available — return error instead of doing the work ourselves
        if best_result is None:
            return JSONResponse(status_code=503, content={
                "error": "No workers available",
                "task_id": task_id,
                "message": "No workers responded. Register as a worker at POST /register-worker.",
            })

        response = VerifyResponse(
            task_id=task_id,
            passed=best_result.get("passed", True),
            confidence=best_result.get("confidence", 0),
            issues=best_result.get("issues", []),
            suggestions=best_result.get("suggestions", []),
            agent_id=best_agent,
            mode=mode,
        )

        results[task_id] = response

        # Log completed job to Supabase (persistent history)
        def _log_completed_job():
            try:
                import json as _json_log
                from agent_market.keys import SUPABASE_URL, SUPABASE_KEY
                import urllib.request as _urllib_req
                log_url = f"{SUPABASE_URL}/rest/v1/completed_jobs"
                log_data = _json_log.dumps({
                    "task_id": task_id,
                    "agent_id": best_agent or "local",
                    "task_type": request.task_type,
                    "passed": best_result.get("passed", True),
                    "confidence": best_result.get("confidence", 0),
                    "issues_count": len(best_result.get("issues", [])),
                    "processing_time": best_result.get("processing_time", 0),
                    "mode": mode,
                }).encode("utf-8")
                log_req = _urllib_req.Request(log_url, data=log_data, method="POST", headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                })
                _urllib_req.urlopen(log_req, timeout=5)
            except Exception as e:
                logger.warning(f"Failed to log completed job: {e}")
        import threading
        threading.Thread(target=_log_completed_job, daemon=True).start()

        # Store report on Filecoin in background (fire-and-forget)
        asyncio.ensure_future(_store_filecoin_background(task_id, response))

        # Create on-chain job record (fire-and-forget)
        _process_onchain_background(task_id, response)

        return response


@app.get("/status/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Check the status of a submitted verification job."""
    if task_id in results:
        return TaskStatus(
            task_id=task_id,
            status="complete",
            result=results[task_id],
        )

    if _manager is not None:
        for task in _manager.task_queue:
            if task["task_id"] == task_id:
                return TaskStatus(task_id=task_id, status="queued")

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
async def register_worker(request: RegisterWorkerRequest):
    """
    Register a worker agent to join the verification network.

    The worker's endpoint must expose a /health route that returns HTTP 200.
    If a manager is attached, the worker is also registered with it for
    job distribution. Otherwise the worker is tracked in standalone mode.
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

    # Register with the manager if one is attached
    if _manager is not None:
        _manager.register_worker(request.agent_id, request.endpoint)

    # Always store in the in-memory registry (deduplicate)
    entry = {
        "agent_id": request.agent_id,
        "endpoint": request.endpoint,
        "strategy": request.strategy,
    }
    _registered_workers[:] = [m for m in _registered_workers if m["agent_id"] != request.agent_id]
    _registered_workers.append(entry)

    # Persist to Supabase (survives manager restarts)
    try:
        from agent_market.keys import SUPABASE_URL, SUPABASE_KEY
        import urllib.request as _urllib_req
        upsert_url = f"{SUPABASE_URL}/rest/v1/registered_workers"
        upsert_data = json.dumps({
            "agent_id": request.agent_id,
            "endpoint": request.endpoint,
            "strategy": request.strategy or "default",
            "is_active": True,
        }).encode("utf-8")
        upsert_req = _urllib_req.Request(upsert_url, data=upsert_data, method="POST", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        })
        _urllib_req.urlopen(upsert_req, timeout=5)
    except Exception as e:
        logger.warning(f"Failed to persist worker to Supabase: {e}")

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
async def register_manager(request: RegisterManagerRequest):
    """
    Register a manager agent in the network registry.

    Managers are tracked in an in-memory list so the /network endpoint
    can report who is participating.
    """
    entry = {
        "manager_id": request.manager_id,
        "endpoint": request.endpoint,
    }
    # Deduplicate in-memory
    _registered_managers[:] = [m for m in _registered_managers if m["manager_id"] != request.manager_id]
    _registered_managers.append(entry)

    # Persist to Supabase (same table as workers, with role=manager)
    try:
        from agent_market.keys import SUPABASE_URL, SUPABASE_KEY
        import urllib.request as _ureq
        import json as _json
        upsert_url = f"{SUPABASE_URL}/rest/v1/registered_miners"
        upsert_data = _json.dumps({
            "agent_id": request.manager_id,
            "endpoint": request.endpoint,
            "strategy": "manager",
            "role": "manager",
            "is_active": True,
        }).encode("utf-8")
        req = _ureq.Request(upsert_url, data=upsert_data, method="POST", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        })
        _ureq.urlopen(req, timeout=5)
        logger.info(f"Manager {request.manager_id} persisted to Supabase")
    except Exception as e:
        logger.warning(f"Failed to persist manager to Supabase: {e}")

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
    all_workers = list(_registered_workers)
    onchain_workers = _registry.get_active_workers()
    # Add on-chain workers not already in memory
    known_ids = {m["agent_id"] for m in all_workers}
    for m in onchain_workers:
        if m["agent_id"] not in known_ids:
            all_workers.append(m)

    return NetworkStatus(
        managers=list(_registered_managers),
        workers=all_workers,
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
    task_type: str = Field(default="code-verification", description="Task type: code-verification | text-review | image-analysis")
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
    task_id = str(uuid4())
    desc_hash = hashlib.sha256(f"{request.title}:{task_id}".encode()).digest()

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
        "task_id": task_id,
        "title": request.title,
        "description": request.description,
        "task_type": request.task_type,
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
            "task_id": task_id,
            "title": request.title,
            "task_type": request.task_type,
            "on_chain_job_id": on_chain_id,
        },
    )

    return {
        "success": True,
        "task_id": task_id,
        "on_chain_job_id": on_chain_id,
        "on_chain_tx": job_result.get("tx_hash") if job_result else None,
        "title": request.title,
        "task_type": request.task_type,
        "status": "open",
        "claim_via_api": f"POST /jobs/{task_id}/claim",
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
                "task_id": sj["task_id"],
                "on_chain_job_id": on_chain_id,
                "title": sj["title"],
                "task_type": sj["task_type"],
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


@app.post("/jobs/{task_id}/claim")
async def claim_marketplace_job(task_id: str, raw_request: Request = None):
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
    jobs = _supabase_get(f"marketplace_jobs?task_id=eq.{task_id}&select=*") or []
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

    # Check if already claimed by another worker
    claimed_by = job.get("claimed_by")
    claimed_at = job.get("claimed_at")
    claim_stale = False

    if claimed_by and claimed_at:
        # Check if claim is stale (>10 minutes old)
        try:
            from datetime import datetime
            claim_time = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
            age_seconds = (datetime.now(claim_time.tzinfo) - claim_time).total_seconds()
            claim_stale = age_seconds > 600  # 10 minutes
        except Exception:
            claim_stale = True  # Can't parse, treat as stale

    if claimed_by and not claim_stale and claimed_by != claimer_id:
        return JSONResponse(status_code=409, content={
            "error": "Job already claimed",
            "claimed_by": claimed_by,
            "message": "This job is reserved by another worker. Try a different job or wait for the claim to expire (10 min).",
        })

    # Reserve the job
    try:
        from datetime import datetime, timezone
        _supabase_patch(f"marketplace_jobs?task_id=eq.{task_id}", {
            "claimed_by": claimer_id,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning(f"Failed to persist claim: {e}")

    return {
        "success": True,
        "task_id": task_id,
        "on_chain_job_id": on_chain_id,
        "claimed_by": claimer_id,
        "claim_expires_in": "10 minutes",
        "title": job["title"],
        "task_type": job["task_type"],
        "intent": job["intent"],
        "code": job.get("code", ""),
        "text": job.get("text_content", ""),
        "budget_avnc": float(job.get("budget_avnc", 0)),
        "status": status,
        "submit_via_api": f"POST /jobs/{task_id}/submit",
        "submit_on_chain": f"AgenticCommerceV2.submit({on_chain_id}, deliverableHash)" if on_chain_id else None,
    }


@app.post("/jobs/{task_id}/submit")
async def submit_marketplace_job(task_id: str, raw_request: Request = None):
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
    jobs = _supabase_get(f"marketplace_jobs?task_id=eq.{task_id}&select=*") or []
    if not jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})

    job = jobs[0]

    # Prevent double-submit — check if already completed
    existing = _supabase_get(f"completed_jobs?task_id=eq.{task_id}&select=task_id") or []
    if existing:
        return JSONResponse(status_code=400, content={
            "error": "Job already completed",
            "task_id": task_id,
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
                    "task_id": task_id,
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
            "task_id": task_id,
            "on_chain_job_id": job.get("on_chain_job_id"),
            "task_type": job["task_type"],
            "issues_found": len(result.get("issues", [])),
            "confidence": result.get("confidence", 0),
        },
    )

    # Log to completed_jobs in Supabase
    import threading
    def _log_marketplace_completion():
        try:
            import json as _jlog
            from agent_market.keys import SUPABASE_URL, SUPABASE_KEY
            import urllib.request as _ureq
            log_url = f"{SUPABASE_URL}/rest/v1/completed_jobs"
            log_data = _jlog.dumps({
                "task_id": task_id,
                "agent_id": submitter_name or body.get("agent_id") or "marketplace-submitter",
                "task_type": job.get("task_type", "code-verification"),
                "passed": result.get("passed", True),
                "confidence": result.get("confidence", 0),
                "issues_count": len(result.get("issues", [])),
                "mode": "marketplace",
            }).encode("utf-8")
            req = _ureq.Request(log_url, data=log_data, method="POST", headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            })
            _ureq.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to log marketplace job completion: {e}")
    threading.Thread(target=_log_marketplace_completion, daemon=True).start()

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
        "task_id": task_id,
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
        is_manager = "manager" in strategy.lower()
        agents.append({
            "agent_id": m["agent_id"],
            "role": "manager" if is_manager else "worker",
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
                    "/jobs/submit": "Submit a job for verification (costs 1 credit per call)",
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
    """API key usage statistics for this manager."""
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
            f"completed_jobs?agent_id=eq.{agent_id}&order=created_at.desc&limit={limit}&select=task_id,task_type,passed,confidence,issues_count,processing_time,mode,created_at"
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
    rows = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&select=agent_name,earnings,withdraw_address")
    if not rows:
        return JSONResponse(status_code=401, content={"error": "Invalid API key"})

    row = rows[0]
    return {
        "agent_name": row.get("agent_name"),
        "earnings": float(row.get("earnings", 0) or 0),
        "withdraw_address": row.get("withdraw_address"),
        "currency": "AVNC",
        "note": "Use POST /withdraw to send earnings to your wallet",
    }


@app.post("/withdraw")
async def withdraw_earnings(raw_request: Request):
    """Withdraw AVNC earnings to a wallet address. Requires API key."""
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
        'POST /jobs/submit with {"code": "...", "intent": "...", "task_type": "code-verification"}\n'
        'POST /jobs/submit with {"image": "<base64>", "intent": "...", "task_type": "image-analysis"}\n\n'
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
            "/status/{task_id}": "GET — Check task status",
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
