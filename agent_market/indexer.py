"""
Event Indexer — watches AgenticCommerceV3 on-chain events and syncs to Supabase.

This ensures that jobs created/funded/completed directly on-chain
(without going through the API) still appear in Supabase for the frontend.

Runs as a background asyncio task inside the manager process.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

COMMERCE_DEPLOYED_PATH = Path(__file__).parent.parent / "contracts" / "commerce_v2_deployed.json"
POLL_INTERVAL = 15  # seconds between polls
REORG_BUFFER = 10   # re-scan last N blocks for safety


class EventIndexer:
    """Watches AgenticCommerceV3 for events and syncs to Supabase."""

    def __init__(self):
        self.enabled = False
        self.w3 = None
        self.contract = None
        self._task: Optional[asyncio.Task] = None
        self._last_block: int = 0

        if not COMMERCE_DEPLOYED_PATH.exists():
            logger.info("No commerce_v2_deployed.json — event indexer disabled")
            return

        try:
            from web3 import Web3

            with open(COMMERCE_DEPLOYED_PATH) as f:
                info = json.load(f)

            rpc_url = os.environ.get("BASE_RPC_URL", "")
            if not rpc_url:
                logger.info("No BASE_RPC_URL — event indexer disabled")
                return

            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            if not self.w3.is_connected():
                logger.warning("Cannot connect to RPC — event indexer disabled")
                return

            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(info["address"]),
                abi=info["abi"],
            )
            self.enabled = True
            logger.info(f"Event indexer enabled: watching {info['address']}")

        except Exception as e:
            logger.warning(f"Failed to initialize event indexer: {e}")

    async def start(self):
        """Start the indexer as a background task."""
        if not self.enabled:
            return

        # Load last processed block from Supabase
        await self._load_last_block()

        async def _loop():
            while True:
                try:
                    await self._poll()
                except Exception as e:
                    logger.error(f"Event indexer poll error: {e}")
                await asyncio.sleep(POLL_INTERVAL)

        self._task = asyncio.create_task(_loop())
        logger.info(f"Event indexer started, polling every {POLL_INTERVAL}s from block {self._last_block}")

    async def _load_last_block(self):
        """Load last processed block from Supabase."""
        try:
            from agent_market.keys import _supabase_get
            rows = _supabase_get("indexer_state?id=eq.1&select=last_block")
            if rows:
                self._last_block = rows[0]["last_block"]
                logger.info(f"Indexer resuming from block {self._last_block}")
            else:
                # First run — start from current block minus buffer
                self._last_block = max(0, self.w3.eth.block_number - 1000)
                logger.info(f"Indexer first run, starting from block {self._last_block}")
        except Exception as e:
            logger.warning(f"Failed to load indexer state (table may not exist yet): {e}")
            try:
                self._last_block = max(0, self.w3.eth.block_number - 100)
            except Exception:
                self._last_block = 0

    async def _save_last_block(self, block: int):
        """Save last processed block to Supabase."""
        try:
            from agent_market.supabase_writer import writer
            await writer.upsert("indexer_state", {
                "id": 1,
                "last_block": block,
            }, on_conflict="id")
            self._last_block = block
        except Exception as e:
            logger.warning(f"Failed to save indexer state: {e}")

    async def _poll(self):
        """Poll for new events since last block."""
        if not self.w3 or not self.contract:
            return

        current_block = self.w3.eth.block_number
        # Apply reorg buffer
        from_block = max(0, self._last_block - REORG_BUFFER)
        to_block = current_block

        if from_block >= to_block:
            return

        # Process each event type
        event_handlers = {
            "JobCreated": self._handle_job_created,
            "JobFunded": self._handle_job_funded,
            "JobSubmitted": self._handle_job_submitted,
            "JobCompleted": self._handle_job_completed,
            "JobRejected": self._handle_job_rejected,
        }

        for event_name, handler in event_handlers.items():
            try:
                event_filter = getattr(self.contract.events, event_name)
                logs = event_filter.get_logs(fromBlock=from_block, toBlock=to_block)
                for log in logs:
                    await handler(log)
            except Exception as e:
                logger.warning(f"Failed to process {event_name} events: {e}")

        await self._save_last_block(to_block)

    async def _handle_job_created(self, log):
        """Handle JobCreated(jobId, client, manager, budget) event."""
        from agent_market.supabase_writer import writer
        args = log.args
        job_id = args.get("jobId", args.get("jobID", 0))
        await writer.upsert("marketplace_jobs", {
            "on_chain_job_id": job_id,
            "job_id": f"onchain-{job_id}",
            "title": f"On-chain Job #{job_id}",
            "job_type": "code-verification",
            "intent": "On-chain job",
            "budget_avnc": 0,
            "on_chain_status": "Open",
        }, on_conflict="on_chain_job_id")
        logger.info(f"Indexed JobCreated #{job_id}")

    async def _handle_job_funded(self, log):
        """Handle JobFunded(jobId, client, amount) event."""
        from agent_market.supabase_writer import writer
        args = log.args
        job_id = args.get("jobId", args.get("jobID", 0))
        amount = args.get("amount", 0)

        # Convert from wei to AVNC (18 decimals)
        try:
            from web3 import Web3
            amount_avnc = float(Web3.from_wei(amount, "ether"))
        except Exception:
            amount_avnc = amount

        await writer.upsert("marketplace_jobs", {
            "on_chain_job_id": job_id,
            "job_id": f"onchain-{job_id}",
            "on_chain_status": "Funded",
            "budget_avnc": amount_avnc,
            "funded_amount": amount,
        }, on_conflict="on_chain_job_id")
        logger.info(f"Indexed JobFunded #{job_id}, amount={amount_avnc}")

    async def _handle_job_submitted(self, log):
        """Handle JobSubmitted(jobId, worker, deliverable) event."""
        from agent_market.supabase_writer import writer
        args = log.args
        job_id = args.get("jobId", args.get("jobID", 0))
        worker = args.get("worker", "")

        await writer.upsert("marketplace_jobs", {
            "on_chain_job_id": job_id,
            "job_id": f"onchain-{job_id}",
            "on_chain_status": "Submitted",
            "worker_address": str(worker),
        }, on_conflict="on_chain_job_id")
        logger.info(f"Indexed JobSubmitted #{job_id}, worker={worker}")

    async def _handle_job_completed(self, log):
        """Handle JobCompleted(jobId, worker, payout, fee) event."""
        from agent_market.supabase_writer import writer
        args = log.args
        job_id = args.get("jobId", args.get("jobID", 0))
        worker = args.get("worker", "")
        payout = args.get("payout", 0)
        fee = args.get("fee", 0)

        await writer.upsert("marketplace_jobs", {
            "on_chain_job_id": job_id,
            "job_id": f"onchain-{job_id}",
            "on_chain_status": "Completed",
            "worker_address": str(worker),
            "payout": payout,
            "fee": fee,
        }, on_conflict="on_chain_job_id")

        # Also log to completed_jobs for leaderboard
        await writer.write("completed_jobs", {
            "job_id": f"onchain-{job_id}",
            "agent_id": str(worker),
            "job_type": "on-chain",
            "passed": True,
            "confidence": 1.0,
            "issues_count": 0,
            "mode": "on-chain",
        })
        logger.info(f"Indexed JobCompleted #{job_id}, worker={worker}")

    async def _handle_job_rejected(self, log):
        """Handle JobRejected(jobId, client, refund) event."""
        from agent_market.supabase_writer import writer
        args = log.args
        job_id = args.get("jobId", args.get("jobID", 0))

        await writer.upsert("marketplace_jobs", {
            "on_chain_job_id": job_id,
            "job_id": f"onchain-{job_id}",
            "on_chain_status": "Rejected",
        }, on_conflict="on_chain_job_id")
        logger.info(f"Indexed JobRejected #{job_id}")
