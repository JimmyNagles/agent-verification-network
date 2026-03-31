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
        self.task_queue: List[dict] = []
        self.results: Dict[str, dict] = {}  # task_id -> result
        self.worker_agents: List[dict] = []  # registered worker endpoints
        self.worker_job_counts: Dict[str, int] = {}  # agent_id -> jobs completed
        self.round_count = 0
        self.PROBATION_THRESHOLD = 20  # jobs before full worker status

    def register_worker(self, agent_id: str, endpoint: str):
        """Register a worker agent to receive jobs."""
        self.worker_agents.append({
            "agent_id": agent_id,
            "endpoint": endpoint,
        })
        self.scores[agent_id] = 0.0
        logger.info(f"Registered worker: {agent_id} at {endpoint}")

    def add_task(self, code: str, intent: str, language: str = "python") -> str:
        """Add an external task to the queue. Returns task_id."""
        task_id = str(uuid4())
        self.task_queue.append({
            "task_id": task_id,
            "code": code,
            "intent": intent,
            "language": language,
            "is_spot_check": False,
            "known_bugs": None,
        })
        return task_id

    def get_result(self, task_id: str) -> Optional[dict]:
        """Get result for a completed task."""
        return self.results.get(task_id)

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

        if self.task_queue and random.random() > spot_check_rate:
            task = self.task_queue.pop(0)
        else:
            # Generate spot check — 85% code, 15% image
            if random.random() < 0.15:
                image_b64, intent, known_bugs = self.image_spot_check_gen.generate()
                task = {
                    "task_id": str(uuid4()),
                    "code": "",
                    "image": image_b64,
                    "intent": intent,
                    "language": "python",
                    "task_type": "image-analysis",
                    "is_spot_check": True,
                    "known_bugs": known_bugs,
                }
            else:
                code, intent, known_bugs = self.spot_check_gen.generate()
                task = {
                    "task_id": str(uuid4()),
                    "code": code,
                    "intent": intent,
                    "language": "python",
                    "task_type": "code-verification",
                    "is_spot_check": True,
                    "known_bugs": known_bugs,
                }

        request = JobRequest(
            code=task.get("code", ""),
            image=task.get("image", ""),
            intent=task["intent"],
            language=task.get("language", "python"),
            task_id=task["task_id"],
            task_type=task.get("task_type", "code-verification"),
        )

        # Collect ALL responses from workers first (needed for consensus)
        responses = await self._query_workers(request)

        if not responses:
            return {
                "round": self.round_count,
                "task_id": task["task_id"],
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
            self.results[task["task_id"]] = {
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
            "task_id": task["task_id"],
            "is_spot_check": task["is_spot_check"],
            "responses": len(responses),
            "best_agent": best_agent,
            "best_score": best_score,
            "scores": round_scores,
            "gate_results": gate_results,
        }

    async def _query_workers(self, request: JobRequest) -> Dict[str, JobResponse]:
        """
        Send a job request to all registered workers.

        In production, this makes HTTP calls to worker endpoints.
        """
        responses = {}

        if not self.worker_agents:
            # No workers registered — manager never does analysis itself
            logger.warning("No workers registered — cannot process job")
            return responses

        # Production mode — HTTP calls to worker endpoints
        import urllib.request
        import json

        for worker in self.worker_agents:
            try:
                data = json.dumps({
                    "code": request.code,
                    "image": request.image,
                    "intent": request.intent,
                    "language": request.language,
                    "task_type": request.task_type,
                    "task_id": request.task_id,
                }).encode("utf-8")

                req = urllib.request.Request(
                    f"{worker['endpoint']}/verify",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))

                responses[worker["agent_id"]] = JobResponse(
                    task_id=result.get("task_id", request.task_id),
                    issues=result.get("issues", []),
                    confidence=result.get("confidence", 0.0),
                    passed=result.get("passed", True),
                    suggestions=result.get("suggestions", []),
                    processing_time=result.get("processing_time", 0.0),
                    agent_id=worker["agent_id"],
                )
            except Exception as e:
                logger.warning(f"Worker {worker['agent_id']} failed: {e}")

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
