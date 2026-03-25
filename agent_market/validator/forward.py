"""
Validator Forward — The validator agent's main loop.

Generates honeypot tasks, sends them to miner agents, scores responses,
and records scores on-chain. This replaces the Bittensor validator loop
with a chain-agnostic design that can write to Base via standard web3.
"""

import asyncio
import logging
import random
import time
from typing import Dict, List, Optional
from uuid import uuid4

from agent_market.protocol import CodeVerificationRequest, CodeVerificationResponse
from agent_market.validator.honeypot import HoneypotGenerator
from agent_market.validator.image_honeypot import ImageHoneypotGenerator
from agent_market.validator.scorer import MinerScorer

logger = logging.getLogger(__name__)


class ValidatorForward:
    """
    Validator agent that:
    1. Generates honeypot code with known bugs
    2. Sends verification tasks to registered miner agents
    3. Scores miner responses against ground truth
    4. Records scores (in-memory for now, on-chain when connected)
    """

    def __init__(self):
        self.honeypot_gen = HoneypotGenerator()
        self.image_honeypot_gen = ImageHoneypotGenerator()
        self.scorer = MinerScorer()
        self.scores: Dict[str, float] = {}  # agent_id -> running score
        self.task_queue: List[dict] = []
        self.results: Dict[str, dict] = {}  # task_id -> result
        self.miner_agents: List[dict] = []  # registered miner endpoints
        self.round_count = 0

    def register_miner(self, agent_id: str, endpoint: str):
        """Register a miner agent to receive tasks."""
        self.miner_agents.append({
            "agent_id": agent_id,
            "endpoint": endpoint,
        })
        self.scores[agent_id] = 0.0
        logger.info(f"Registered miner: {agent_id} at {endpoint}")

    def add_task(self, code: str, intent: str, language: str = "python") -> str:
        """Add an external task to the queue. Returns task_id."""
        task_id = str(uuid4())
        self.task_queue.append({
            "task_id": task_id,
            "code": code,
            "intent": intent,
            "language": language,
            "is_honeypot": False,
            "known_bugs": None,
        })
        return task_id

    def get_result(self, task_id: str) -> Optional[dict]:
        """Get result for a completed task."""
        return self.results.get(task_id)

    async def run_round(self):
        """
        Run one validation round:
        1. Pick a task (honeypot or real)
        2. Send to all miners
        3. Score responses
        4. Update scores
        """
        self.round_count += 1
        logger.info(f"=== Validation round {self.round_count} ===")

        # Decide: honeypot or real task
        if self.task_queue and random.random() > 0.3:
            task = self.task_queue.pop(0)
        else:
            # Generate honeypot — 85% code, 15% image
            if random.random() < 0.15:
                image_b64, intent, known_bugs = self.image_honeypot_gen.generate()
                task = {
                    "task_id": str(uuid4()),
                    "code": "",
                    "image": image_b64,
                    "intent": intent,
                    "language": "python",
                    "task_type": "image-analysis",
                    "is_honeypot": True,
                    "known_bugs": known_bugs,
                }
            else:
                code, intent, known_bugs = self.honeypot_gen.generate()
                task = {
                    "task_id": str(uuid4()),
                    "code": code,
                    "intent": intent,
                    "language": "python",
                    "task_type": "code-verification",
                    "is_honeypot": True,
                    "known_bugs": known_bugs,
                }

        request = CodeVerificationRequest(
            code=task.get("code", ""),
            image=task.get("image", ""),
            intent=task["intent"],
            language=task.get("language", "python"),
            task_id=task["task_id"],
            task_type=task.get("task_type", "code-verification"),
        )

        # Collect responses from all miners
        responses = await self._query_miners(request)

        # Score each response
        best_score = -1
        best_response = None
        best_agent = None

        for agent_id, response in responses.items():
            score = self.scorer.score(
                response_issues=response.issues,
                response_passed=response.passed,
                response_confidence=response.confidence,
                response_time=response.processing_time,
                is_honeypot=task["is_honeypot"],
                known_bugs=task["known_bugs"],
            )

            # Exponential moving average
            old_score = self.scores.get(agent_id, 0.0)
            self.scores[agent_id] = 0.9 * old_score + 0.1 * score

            logger.info(f"  {agent_id}: score={score:.3f} (running={self.scores[agent_id]:.3f})")

            if score > best_score:
                best_score = score
                best_response = response
                best_agent = agent_id

        # Store result for real tasks
        if not task["is_honeypot"] and best_response:
            self.results[task["task_id"]] = {
                "passed": best_response.passed,
                "confidence": best_response.confidence,
                "issues": best_response.issues,
                "suggestions": best_response.suggestions,
                "agent_id": best_agent,
                "score": best_score,
            }

        return {
            "round": self.round_count,
            "task_id": task["task_id"],
            "is_honeypot": task["is_honeypot"],
            "responses": len(responses),
            "best_agent": best_agent,
            "best_score": best_score,
        }

    async def _query_miners(self, request: CodeVerificationRequest) -> Dict[str, CodeVerificationResponse]:
        """
        Send a verification request to all registered miners.

        For local/demo mode, this imports and calls the miner forward directly.
        In production, this would make HTTP calls to miner endpoints.
        """
        responses = {}

        if not self.miner_agents:
            # No miners registered — validator never does analysis itself
            logger.warning("No miners registered — cannot process task")
            return responses

        # Production mode — HTTP calls to miner endpoints
        import urllib.request
        import json

        for miner in self.miner_agents:
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
                    f"{miner['endpoint']}/verify",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))

                responses[miner["agent_id"]] = CodeVerificationResponse(
                    task_id=result.get("task_id", request.task_id),
                    issues=result.get("issues", []),
                    confidence=result.get("confidence", 0.0),
                    passed=result.get("passed", True),
                    suggestions=result.get("suggestions", []),
                    processing_time=result.get("processing_time", 0.0),
                    agent_id=miner["agent_id"],
                )
            except Exception as e:
                logger.warning(f"Miner {miner['agent_id']} failed: {e}")

        return responses

    async def run_loop(self, interval: int = 30, rounds: Optional[int] = None):
        """Run the validator loop continuously or for N rounds."""
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
