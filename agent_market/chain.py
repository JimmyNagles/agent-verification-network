"""
On-chain scoring — writes agent scores to AgentScorer.sol on Base.

Loads deployment info from contracts/deployed.json. If no contract is
deployed or no private key is set, all calls are no-ops so the system
works in standalone mode without any chain dependency.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEPLOYED_PATH = Path(__file__).parent.parent / "contracts" / "deployed.json"


class ChainScorer:
    """Write scores to AgentScorer.sol on Base Sepolia."""

    def __init__(self):
        self.enabled = False
        self.w3 = None
        self.contract = None
        self.account = None

        private_key = os.environ.get("PRIVATE_KEY")
        if not private_key:
            logger.info("PRIVATE_KEY not set — on-chain scoring disabled")
            return

        if not DEPLOYED_PATH.exists():
            logger.info("No contracts/deployed.json — on-chain scoring disabled")
            return

        try:
            from web3 import Web3

            with open(DEPLOYED_PATH) as f:
                info = json.load(f)

            self.w3 = Web3(Web3.HTTPProvider(info["rpc"]))
            if not self.w3.is_connected():
                logger.warning("Cannot connect to RPC — on-chain scoring disabled")
                return

            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(info["address"]),
                abi=info["abi"],
            )
            self.account = self.w3.eth.account.from_key(private_key)
            # Detect chain from deployed.json or default to mainnet
            self.chain_id = info.get("chain_id", 8453 if "mainnet" in info.get("chain", "") else 84532)
            self.enabled = True
            logger.info(f"On-chain scoring enabled: contract={info['address']}")

        except Exception as e:
            logger.warning(f"Failed to initialize chain scorer: {e}")

    def record_score(
        self,
        agent_id: str,
        task_id: str,
        score: float,
        round_num: int,
    ) -> Optional[dict]:
        """Write a score on-chain. Returns tx info or None if disabled."""
        if not self.enabled:
            return None

        try:
            # Convert float score to uint (score * 10000)
            score_uint = int(score * 10000)

            tx = self.contract.functions.recordScore(
                agent_id, task_id, score_uint, round_num
            ).build_transaction({
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.chain_id,
            })

            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            result = {
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.blockNumber,
                "chain": "base-sepolia",
                "contract": self.contract.address,
                "gas_used": receipt.gasUsed,
            }
            logger.info(f"Score recorded on-chain: tx={tx_hash.hex()}")
            return result

        except Exception as e:
            logger.error(f"On-chain score recording failed: {e}")
            return None
