#!/usr/bin/env python3
"""
Validator Agent — Standalone runner for the verification validator.

Starts the API server in connected mode, registers miners, and runs
the validation loop (honeypot generation, task distribution, scoring).
Logs all activity to agent_log.json.

Usage:
    python -m agents.validator_agent [--port 8000] [--rounds 10] [--miners http://localhost:8001]
"""

import argparse
import asyncio
import logging
import sys
import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI

from agent_market.api.server import app as api_app, attach_validator
from agent_market.validator.forward import ValidatorForward
from agent_market.logger import log_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("validator-agent")


class LoggingValidator(ValidatorForward):
    """Extends ValidatorForward with event logging to agent_log.json and on-chain scoring."""

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
            "task_id": result["task_id"],
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
                task_id=result["task_id"],
                score=result["best_score"],
                round_num=result["round"],
            )
            if chain_result:
                details["on_chain"] = chain_result

        log_event(
            event_type="validation_round",
            agent_role="validator",
            agent_id=self.agent_id,
            details=details,
        )

        return result


async def run_validator(agent_id: str, rounds: int, interval: int, miner_endpoints: list, use_chain: bool = False):
    """Run the validator loop."""
    validator = LoggingValidator(agent_id, use_chain=use_chain)

    # Register miners
    for i, endpoint in enumerate(miner_endpoints):
        miner_id = f"miner-{i+1:03d}"
        validator.register_miner(miner_id, endpoint)
        log_event(
            event_type="miner_registered",
            agent_role="validator",
            agent_id=agent_id,
            details={"miner_id": miner_id, "endpoint": endpoint},
        )

    # Attach to API server so /verify routes through the network
    attach_validator(validator)

    log_event(
        event_type="agent_started",
        agent_role="validator",
        agent_id=agent_id,
        details={
            "miners_registered": len(miner_endpoints),
            "rounds_planned": rounds,
            "mode": "connected" if miner_endpoints else "demo",
        },
    )

    logger.info(f"Validator {agent_id} starting: {rounds} rounds, {len(miner_endpoints)} miners")

    # Run validation rounds
    for i in range(rounds):
        try:
            result = await validator.run_round()
            logger.info(
                f"Round {result['round']}: "
                f"{'honeypot' if result['is_honeypot'] else 'real'} | "
                f"best={result['best_agent']} score={result['best_score']:.3f}"
            )
        except Exception as e:
            logger.error(f"Round {i+1} failed: {e}")

        if i < rounds - 1:
            await asyncio.sleep(interval)

    # Log final scores
    log_event(
        event_type="validation_complete",
        agent_role="validator",
        agent_id=agent_id,
        details={
            "rounds_completed": validator.round_count,
            "final_scores": {
                aid: round(s, 4) for aid, s in sorted(
                    validator.scores.items(), key=lambda x: x[1], reverse=True
                )
            },
        },
    )

    logger.info(f"Validation complete. Final scores: {validator.scores}")
    return validator


def main():
    parser = argparse.ArgumentParser(description="Run a validator agent")
    parser.add_argument("--port", type=int, default=8000, help="API server port")
    parser.add_argument("--agent-id", default=f"validator-{uuid4().hex[:8]}", help="Agent identifier")
    parser.add_argument("--rounds", type=int, default=10, help="Number of validation rounds")
    parser.add_argument("--interval", type=int, default=2, help="Seconds between rounds")
    parser.add_argument("--miners", nargs="*", default=[], help="Miner endpoint URLs")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--no-server", action="store_true", help="Run validator loop without API server")
    parser.add_argument("--chain", action="store_true", help="Enable on-chain score recording (requires PRIVATE_KEY env var and contracts/deployed.json)")
    args = parser.parse_args()

    logger.info(f"Starting validator agent: {args.agent_id}")

    if args.no_server:
        # Just run the validation loop
        asyncio.run(run_validator(args.agent_id, args.rounds, args.interval, args.miners, use_chain=args.chain))
    else:
        # Run both API server and validator loop
        import threading

        def start_validation():
            # Give the server a moment to start
            import time
            time.sleep(2)
            asyncio.run(run_validator(args.agent_id, args.rounds, args.interval, args.miners, use_chain=args.chain))

        thread = threading.Thread(target=start_validation, daemon=True)
        thread.start()

        uvicorn.run(api_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
