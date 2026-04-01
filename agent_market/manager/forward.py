"""
Manager Forward — The manager agent's main loop.

Generates spot check jobs, sends them to worker agents, scores responses,
and records ratings on-chain. This replaces the Bittensor manager loop
with a chain-agnostic design that can write to Base via standard web3.
"""

import asyncio
import logging
import random
import time
from typing import Dict, List, Optional
from uuid import uuid4

from agent_market.protocol import JobRequest, JobResponse
from agent_market.manager.spot_check import SpotCheckGenerator
from agent_market.manager.image_spot_check import ImageSpotCheckGenerator
from agent_market.manager.scorer import WorkerScorer

logger = logging.getLogger(__name__)


class ManagerForward:
    """
    Manager agent that:
    1. Generates spot check jobs with known bugs
    2. Sends jobs to registered worker agents
    3. Scores worker responses against ground truth
    4. Records ratings (in-memory for now, on-chain when connected)
    """

    def __init__(self):
        self.spot_check_gen = SpotCheckGenerator()
        self.image_spot_check_gen = ImageSpotCheckGenerator()
        self.scorer = WorkerScorer()
        self.scores: Dict[str, float] = {}  # agent_id -> running score
        self.job_queue: List[dict] = []
        self.results: Dict[str, dict] = {}  # job_id -> result
        self.worker_agents: List[dict] = []  # registered worker endpoints
        self.worker_job_counts: Dict[str, int] = {}  # agent_id -> jobs completed
        self.round_count = 0
        self.PROBATION_THRESHOLD = 20  # jobs before full worker status
        self._load_scores_from_supabase()

    def register_worker(self, agent_id: str, endpoint: str, strategy: str = ""):
        """Register a worker agent to receive jobs."""
        # Deduplicate
        self.worker_agents = [w for w in self.worker_agents if w["agent_id"] != agent_id]
        self.worker_agents.append({
            "agent_id": agent_id,
            "endpoint": endpoint,
            "strategy": strategy,
        })
        if agent_id not in self.scores:
            self.scores[agent_id] = 0.0
        logger.info(f"Registered worker: {agent_id} at {endpoint}")

    def merge_onchain_workers(self, registry):
        """Merge workers from on-chain registry into our worker list."""
        if not registry or not registry.enabled:
            return
        try:
            onchain = registry.get_active_workers()
            known_ids = {w["agent_id"] for w in self.worker_agents}
            for agent in onchain:
                if agent["agent_id"] in known_ids:
                    continue
                strategy = agent.get("strategy", "")
                # Skip managers
                if "manager" in strategy.lower() or "validator" in strategy.lower():
                    continue
                self.worker_agents.append({
                    "agent_id": agent["agent_id"],
                    "endpoint": agent["endpoint"],
                    "strategy": strategy,
                })
        except Exception as e:
            logger.warning(f"Failed to merge on-chain workers: {e}")

    async def route_job(self, request: JobRequest) -> Optional[dict]:
        """
        Route a single job to workers, score responses, return best result.
        This is the single code path for all job routing.

        Returns dict with: passed, confidence, issues, suggestions, agent_id, score, mode
        Returns None if no workers responded.
        """
        # Collect all responses from workers
        responses = await self._query_workers(request)

        if not responses:
            return None

        # Convert to list for consensus scoring
        all_response_list = list(responses.values())

        # Score each response
        best_score = -1
        best_response = None
        best_agent = None
        round_scores = {}

        for agent_id, response in responses.items():
            score = self.scorer.score(
                response_issues=response.issues,
                response_passed=response.passed,
                response_confidence=response.confidence,
                response_time=response.processing_time,
                is_spot_check=False,
                known_bugs=None,
                all_responses=all_response_list if len(all_response_list) > 1 else None,
            )

            # Update running scores
            old_score = self.scores.get(agent_id, 0.0)
            self.scores[agent_id] = 0.9 * old_score + 0.1 * score
            self.worker_job_counts[agent_id] = self.worker_job_counts.get(agent_id, 0) + 1
            round_scores[agent_id] = score

            if score > best_score:
                best_score = score
                best_response = response
                best_agent = agent_id

        if best_response is None:
            return None

        # Persist scores to Supabase in background
        asyncio.ensure_future(self._save_scores_to_supabase(round_scores))

        return {
            "passed": best_response.passed,
            "confidence": best_response.confidence,
            "issues": best_response.issues,
            "suggestions": best_response.suggestions,
            "agent_id": best_agent,
            "score": best_score,
            "processing_time": best_response.processing_time,
            "all_scores": round_scores,
            "mode": "network",
        }

    def _load_scores_from_supabase(self):
        """Load persisted worker scores on startup."""
        try:
            from agent_market.keys import _supabase_get
            rows = _supabase_get("worker_scores?select=agent_id,running_score,jobs_completed")
            if rows:
                for row in rows:
                    self.scores[row["agent_id"]] = row["running_score"]
                    self.worker_job_counts[row["agent_id"]] = row["jobs_completed"]
                logger.info(f"Loaded {len(rows)} worker scores from Supabase")
        except Exception as e:
            logger.warning(f"Failed to load worker scores (table may not exist yet): {e}")

    async def _save_scores_to_supabase(self, round_scores: Dict[str, float]):
        """Persist updated scores to Supabase after a round."""
        try:
            from agent_market.supabase_writer import writer
            for agent_id, score in round_scores.items():
                await writer.upsert("worker_scores", {
                    "agent_id": agent_id,
                    "running_score": round(self.scores.get(agent_id, 0.0), 6),
                    "jobs_completed": self.worker_job_counts.get(agent_id, 0),
                    "last_round": self.round_count,
                }, on_conflict="agent_id")
        except Exception as e:
            logger.warning(f"Failed to save scores to Supabase: {e}")

    def add_task(self, code: str, intent: str, language: str = "python") -> str:
        """Add an external task to the queue. Returns job_id."""
        job_id = str(uuid4())
        self.job_queue.append({
            "job_id": job_id,
            "code": code,
            "intent": intent,
            "language": language,
            "is_spot_check": False,
            "known_bugs": None,
        })
        return job_id

    def get_result(self, job_id: str) -> Optional[dict]:
        """Get result for a completed task."""
        return self.results.get(job_id)

    async def run_round(self):
        """
        Run one validation round:
        1. Pick a task (spot check or real)
        2. Send to all workers
        3. Score responses
        4. Update scores
        """
        self.round_count += 1
        logger.info(f"=== Validation round {self.round_count} ===")

        # Decide: spot check or real task
        # Probation workers (< 20 jobs) get 50% spot checks instead of 30%
        any_on_probation = any(
            self.worker_job_counts.get(w["agent_id"], 0) < self.PROBATION_THRESHOLD
            for w in self.worker_agents
        )
        spot_check_rate = 0.5 if any_on_probation else 0.3

        if self.job_queue and random.random() > spot_check_rate:
            task = self.job_queue.pop(0)
        else:
            # Generate spot check — 85% code, 15% image
            if random.random() < 0.15:
                image_b64, intent, known_bugs = self.image_spot_check_gen.generate()
                task = {
                    "job_id": str(uuid4()),
                    "code": "",
                    "image": image_b64,
                    "intent": intent,
                    "language": "python",
                    "job_type": "image-analysis",
                    "is_spot_check": True,
                    "known_bugs": known_bugs,
                }
            else:
                code, intent, known_bugs = self.spot_check_gen.generate()
                task = {
                    "job_id": str(uuid4()),
                    "code": code,
                    "intent": intent,
                    "language": "python",
                    "job_type": "code-verification",
                    "is_spot_check": True,
                    "known_bugs": known_bugs,
                }

        request = JobRequest(
            code=task.get("code", ""),
            image=task.get("image", ""),
            intent=task["intent"],
            language=task.get("language", "python"),
            job_id=task["job_id"],
            job_type=task.get("job_type", "code-verification"),
        )

        # Collect ALL responses from workers first (needed for consensus)
        responses = await self._query_workers(request)

        if not responses:
            return {
                "round": self.round_count,
                "job_id": task["job_id"],
                "is_spot_check": task["is_spot_check"],
                "responses": 0,
                "best_agent": None,
                "best_score": None,
                "scores": {},
                "gate_results": {},
            }

        # Convert responses to list for consensus scoring
        all_response_list = list(responses.values())

        # Score each response WITH consensus (all_responses passed in)
        best_score = -1
        best_response = None
        best_agent = None
        round_scores = {}
        gate_results = {}

        for agent_id, response in responses.items():
            score = self.scorer.score(
                response_issues=response.issues,
                response_passed=response.passed,
                response_confidence=response.confidence,
                response_time=response.processing_time,
                is_spot_check=task["is_spot_check"],
                known_bugs=task["known_bugs"],
                all_responses=all_response_list,
            )

            # Quality gate check
            passed_gate = self.scorer.passes_gate(score)
            gate_results[agent_id] = passed_gate

            # Exponential moving average
            old_score = self.scores.get(agent_id, 0.0)
            self.scores[agent_id] = 0.9 * old_score + 0.1 * score
            self.worker_job_counts[agent_id] = self.worker_job_counts.get(agent_id, 0) + 1
            round_scores[agent_id] = score

            logger.info(
                f"  {agent_id}: score={score:.3f} "
                f"(running={self.scores[agent_id]:.3f}) "
                f"gate={'PASS' if passed_gate else 'FAIL'}"
            )

            if score > best_score:
                best_score = score
                best_response = response
                best_agent = agent_id

        # Store result for real tasks
        if not task["is_spot_check"] and best_response:
            self.results[task["job_id"]] = {
                "passed": best_response.passed,
                "confidence": best_response.confidence,
                "issues": best_response.issues,
                "suggestions": best_response.suggestions,
                "agent_id": best_agent,
                "score": best_score,
                "gate_passed": gate_results.get(best_agent, False),
                "all_scores": round_scores,
                "all_gate_results": gate_results,
            }

        return {
            "round": self.round_count,
            "job_id": task["job_id"],
            "is_spot_check": task["is_spot_check"],
            "responses": len(responses),
            "best_agent": best_agent,
            "best_score": best_score,
            "scores": round_scores,
            "gate_results": gate_results,
        }

    async def _query_workers(self, request: JobRequest) -> Dict[str, JobResponse]:
        """
        Send a job request to eligible registered workers concurrently.

        Filters workers by job type capability before routing.
        Uses async httpx for non-blocking concurrent requests.
        """
        responses = {}

        if not self.worker_agents:
            logger.warning("No workers registered — cannot process job")
            return responses

        # Filter by job type capability
        job_type = request.job_type or "code-verification"
        eligible = []
        for w in self.worker_agents:
            agent_id = w.get("agent_id", "").lower()
            strategy = w.get("strategy", "").lower()
            is_image_worker = "image" in agent_id or "vision" in agent_id or "image" in strategy or "vision" in strategy
            is_image_job = job_type == "image-analysis"
            if is_image_job and not is_image_worker:
                continue
            if not is_image_job and is_image_worker:
                continue
            eligible.append(w)

        if not eligible:
            eligible = self.worker_agents

        import json
        import httpx

        payload = {
            "code": request.code,
            "image": request.image,
            "intent": request.intent,
            "language": request.language,
            "job_type": request.job_type,
            "job_id": request.job_id,
        }

        async def _call_worker(client: httpx.AsyncClient, worker: dict) -> tuple:
            """Call a single worker and return (agent_id, result_or_none)."""
            agent_id = worker["agent_id"]
            try:
                resp = await client.post(
                    f"{worker['endpoint'].rstrip('/')}/verify",
                    json=payload,
                    timeout=30.0,
                )
                result = resp.json()
                return agent_id, result
            except Exception as e:
                logger.warning(f"Worker {agent_id} failed: {e}")
                return agent_id, None

        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *[_call_worker(client, w) for w in eligible],
                return_exceptions=True,
            )

        for item in results:
            if isinstance(item, Exception):
                continue
            agent_id, result = item
            if result is None:
                continue
            responses[agent_id] = JobResponse(
                job_id=result.get("job_id", request.job_id),
                issues=result.get("issues", []),
                confidence=result.get("confidence", 0.0),
                passed=result.get("passed", True),
                suggestions=result.get("suggestions", []),
                processing_time=result.get("processing_time", 0.0),
                agent_id=agent_id,
            )

        return responses

    async def run_loop(self, interval: int = 30, rounds: Optional[int] = None):
        """Run the manager loop continuously or for N rounds."""
        count = 0
        while rounds is None or count < rounds:
            try:
                result = await self.run_round()
                logger.info(f"Round result: {result}")
            except Exception as e:
                logger.error(f"Round failed: {e}")
            count += 1
            if rounds is None or count < rounds:
                await asyncio.sleep(interval)
