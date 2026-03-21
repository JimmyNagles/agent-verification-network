"""
On-chain job lifecycle — creates and completes jobs on AgenticCommerce.sol.

Loads deployment info from contracts/commerce_deployed.json. If no contract
is deployed or no private key is set, all calls are no-ops so the system
works in standalone mode without any chain dependency.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Prefer V2 (with fee split), fall back to V1
DEPLOYED_PATH_V2 = Path(__file__).parent.parent / "contracts" / "commerce_v2_deployed.json"
DEPLOYED_PATH_V1 = Path(__file__).parent.parent / "contracts" / "commerce_deployed.json"
DEPLOYED_PATH = DEPLOYED_PATH_V2 if DEPLOYED_PATH_V2.exists() else DEPLOYED_PATH_V1


class CommerceClient:
    """Interact with AgenticCommerce.sol on Base."""

    def __init__(self):
        self.enabled = False
        self.w3 = None
        self.contract = None
        self.account = None

        private_key = os.environ.get("PRIVATE_KEY")
        if not private_key:
            logger.info("PRIVATE_KEY not set — commerce integration disabled")
            return

        if not DEPLOYED_PATH.exists():
            logger.info("No contracts/commerce_deployed.json — commerce disabled")
            return

        try:
            from web3 import Web3

            with open(DEPLOYED_PATH) as f:
                info = json.load(f)

            self.w3 = Web3(Web3.HTTPProvider(info["rpc"]))
            if not self.w3.is_connected():
                logger.warning("Cannot connect to RPC — commerce disabled")
                return

            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(info["address"]),
                abi=info["abi"],
            )
            self.account = self.w3.eth.account.from_key(private_key)
            self.chain_id = 8453 if "mainnet" in info.get("chain", "") else 84532
            self.enabled = True
            logger.info(f"Commerce enabled: contract={info['address']}")

        except Exception as e:
            logger.warning(f"Failed to initialize commerce client: {e}")

    def create_job(
        self,
        description_hash: bytes,
        budget_wei: int = 0,
    ) -> Optional[dict]:
        """
        Create a job on-chain. The caller (our wallet) is both client and evaluator
        for network-initiated verification jobs.

        Returns {job_id, tx_hash, block_number} or None if disabled.
        """
        if not self.enabled:
            return None

        try:
            # Use our own address as evaluator, ETH as token, minimal budget
            tx = self.contract.functions.createJob(
                self.account.address,  # evaluator = us
                description_hash,      # bytes32 task descriptor
                "0x0000000000000000000000000000000000000000",  # ETH
                budget_wei if budget_wei > 0 else 1,  # min budget
            ).build_transaction({
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.chain_id,
            })

            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            # Parse job ID from JobCreated event
            job_id = None
            for log in receipt.logs:
                try:
                    event = self.contract.events.JobCreated().process_log(log)
                    job_id = event.args.jobId
                    break
                except Exception:
                    continue

            result = {
                "job_id": job_id,
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.blockNumber,
                "chain": "base-mainnet" if self.chain_id == 8453 else "base-sepolia",
                "contract": self.contract.address,
                "gas_used": receipt.gasUsed,
            }
            logger.info(f"Job created on-chain: job_id={job_id}, tx={tx_hash.hex()}")
            return result

        except Exception as e:
            logger.error(f"On-chain job creation failed: {e}")
            return None

    def complete_job(self, job_id: int) -> Optional[dict]:
        """
        Mark a job as completed on-chain (evaluator approves).
        Returns tx info or None if disabled.
        """
        if not self.enabled:
            return None

        try:
            tx = self.contract.functions.complete(job_id).build_transaction({
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.chain_id,
            })

            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            result = {
                "job_id": job_id,
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.blockNumber,
                "chain": "base-mainnet" if self.chain_id == 8453 else "base-sepolia",
                "gas_used": receipt.gasUsed,
            }
            logger.info(f"Job completed on-chain: job_id={job_id}, tx={tx_hash.hex()}")
            return result

        except Exception as e:
            logger.error(f"On-chain job completion failed: {e}")
            return None

    _cached_job_count: int = 0

    def get_job_count(self) -> int:
        """Get total number of jobs created on-chain. Returns cached value on failure."""
        if not self.enabled:
            return self._cached_job_count
        try:
            count = self.contract.functions.getJobCount().call()
            self._cached_job_count = count
            return count
        except Exception:
            return self._cached_job_count
