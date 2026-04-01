#!/usr/bin/env python3
"""
Manager Agent — Standalone runner for the job manager.

Starts the API server in connected mode, registers workers, and runs
the management loop (spot check generation, job distribution, scoring).
Logs all activity to agent_log.json.

Usage:
    python -m agents.manager_agent [--port 8000] [--rounds 10] [--workers http://localhost:8001]
"""

import argparse
import asyncio
import logging
import sys
import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI

from agent_market.api.server import app as api_app, attach_manager
from agent_market.manager.forward import ManagerForward
from agent_market.logger import log_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("manager-agent")


class LoggingManager(ManagerForward):
    """Extends ManagerForward with event logging to agent_log.json and on-chain scoring."""

    def __init__(self, agent_id: str, use_chain: bool = False):
        super().__init__()
        self.agent_id = agent_id
        self.chain_scorer = None
        if use_chain:
            from agent_market.chain import ChainScorer
            self.chain_scorer = ChainScorer()

    async def run_round(self):
        result = await super().run_round()

        details = {
            "round": result["round"],
            "job_id": result["job_id"],
            "is_honeypot": result["is_honeypot"],
            "responses": result["responses"],
            "best_agent": result["best_agent"],
            "best_score": round(result["best_score"], 4) if result["best_score"] else None,
            "leaderboard": {
                aid: round(s, 4) for aid, s in sorted(
                    self.scores.items(), key=lambda x: x[1], reverse=True
                )[:5]
            },
        }

        # Write score on-chain if enabled
        if self.chain_scorer and self.chain_scorer.enabled and result["best_agent"]:
            chain_result = self.chain_scorer.record_score(
                agent_id=result["best_agent"],
                job_id=result["job_id"],
                score=result["best_score"],
                round_num=result["round"],
            )
            if chain_result:
                details["on_chain"] = chain_result

        log_event(
            event_type="validation_round",
            agent_role="manager",
            agent_id=self.agent_id,
            details=details,
        )

        return result


async def run_manager(agent_id: str, rounds: int, interval: int, worker_endpoints: list, use_chain: bool = False):
    """Run the manager loop."""
    manager = LoggingManager(agent_id, use_chain=use_chain)

    # Register miners
    for i, endpoint in enumerate(worker_endpoints):
        worker_id = f"worker-{i+1:03d}"
        manager.register_worker(worker_id, endpoint)
        log_event(
            event_type="miner_registered",
            agent_role="manager",
            agent_id=agent_id,
            details={"worker_id": worker_id, "endpoint": endpoint},
        )

    # Attach to API server so jobs route through the network
    attach_manager(manager)

    log_event(
        event_type="agent_started",
        agent_role="manager",
        agent_id=agent_id,
        details={
            "workers_registered": len(worker_endpoints),
            "rounds_planned": rounds,
            "mode": "connected" if worker_endpoints else "demo",
        },
    )

    logger.info(f"Manager {agent_id} starting: {rounds} rounds, {len(worker_endpoints)} workers")

    # Run validation rounds
    for i in range(rounds):
        try:
            result = await manager.run_round()
            logger.info(
                f"Round {result['round']}: "
                f"{'spot_check' if result['is_spot_check'] else 'real'} | "
                f"best={result['best_agent']} score={result['best_score']:.3f}"
            )
        except Exception as e:
            logger.error(f"Round {i+1} failed: {e}")

        if i < rounds - 1:
            await asyncio.sleep(interval)

    # Log final scores
    log_event(
        event_type="validation_complete",
        agent_role="manager",
        agent_id=agent_id,
        details={
            "rounds_completed": manager.round_count,
            "final_scores": {
                aid: round(s, 4) for aid, s in sorted(
                    manager.scores.items(), key=lambda x: x[1], reverse=True
                )
            },
        },
    )

    logger.info(f"Management complete. Final ratings: {manager.scores}")
    return manager


def main():
    parser = argparse.ArgumentParser(description="Run a manager agent")
    parser.add_argument("--port", type=int, default=8000, help="API server port")
    parser.add_argument("--agent-id", default=f"manager-{uuid4().hex[:8]}", help="Agent identifier")
    parser.add_argument("--rounds", type=int, default=10, help="Number of validation rounds")
    parser.add_argument("--interval", type=int, default=2, help="Seconds between rounds")
    parser.add_argument("--workers", nargs="*", default=[], help="Worker endpoint URLs")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--no-server", action="store_true", help="Run manager loop without API server")
    parser.add_argument("--chain", action="store_true", help="Enable on-chain score recording (requires PRIVATE_KEY env var and contracts/deployed.json)")
    args = parser.parse_args()

    logger.info(f"Starting manager agent: {args.agent_id}")

    if args.no_server:
        # Just run the validation loop
        asyncio.run(run_manager(args.agent_id, args.rounds, args.interval, args.workers, use_chain=args.chain))
    else:
        # Run both API server and manager loop
        import threading

        def start_validation():
            # Give the server a moment to start
            import time
            time.sleep(2)
            asyncio.run(run_manager(args.agent_id, args.rounds, args.interval, args.workers, use_chain=args.chain))

        thread = threading.Thread(target=start_validation, daemon=True)
        thread.start()

        uvicorn.run(api_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
