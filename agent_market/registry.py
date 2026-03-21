"""
On-chain miner registry — reads and writes to MinerRegistry.sol.

Miners register on-chain once. The registry persists across server restarts.
Anyone can read it to discover miners. No centralized state required.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

DEPLOYED_PATH = Path(__file__).parent.parent / "contracts" / "registry_deployed.json"


class RegistryClient:
    """Interact with MinerRegistry.sol on Base."""

    def __init__(self):
        self.enabled = False
        self.w3 = None
        self.contract = None
        self.account = None

        if not DEPLOYED_PATH.exists():
            logger.info("No contracts/registry_deployed.json — on-chain registry disabled")
            return

        try:
            from web3 import Web3

            with open(DEPLOYED_PATH) as f:
                info = json.load(f)

            self.w3 = Web3(Web3.HTTPProvider(info["rpc"]))
            if not self.w3.is_connected():
                logger.warning("Cannot connect to RPC — registry disabled")
                return

            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(info["address"]),
                abi=info["abi"],
            )
            self.chain_id = 8453 if "mainnet" in info.get("chain", "") else 84532
            self.enabled = True

            # Set up account if private key available (for writing)
            private_key = os.environ.get("PRIVATE_KEY")
            if private_key:
                self.account = self.w3.eth.account.from_key(private_key)

            logger.info(f"Registry enabled: contract={info['address']}")

        except Exception as e:
            logger.warning(f"Failed to initialize registry client: {e}")

    def register_miner(self, agent_id: str, endpoint: str, strategy: str = "") -> Optional[dict]:
        """Register a miner on-chain. Returns tx info or None."""
        if not self.enabled or not self.account:
            return None

        try:
            # Check if already registered
            idx = self.contract.functions.agentIndex(agent_id).call()
            if idx > 0:
                logger.info(f"Miner {agent_id} already registered on-chain")
                return {"already_registered": True, "agent_id": agent_id}

            tx = self.contract.functions.register(
                agent_id, endpoint, strategy or ""
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
                "agent_id": agent_id,
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.blockNumber,
                "chain": "base-mainnet" if self.chain_id == 8453 else "base-sepolia",
            }
            logger.info(f"Miner registered on-chain: {agent_id}, tx={tx_hash.hex()}")
            return result

        except Exception as e:
            logger.error(f"On-chain miner registration failed: {e}")
            return None

    _cached_miners: List[Dict] = []
    _cache_time: float = 0

    def get_active_miners(self) -> List[Dict]:
        """Read all active miners from the on-chain registry. Cached for 60s."""
        import time

        # Return cache if fresh (within 60 seconds)
        if time.time() - self._cache_time < 60 and self._cached_miners:
            return self._cached_miners

        if not self.enabled:
            return self._cached_miners  # Return last known state

        try:
            count = self.contract.functions.getMinerCount().call()
            miners = []
            for i in range(count):
                agent_id, endpoint, strategy, owner, registered_at, active = \
                    self.contract.functions.getMiner(i).call()
                if active:
                    miners.append({
                        "agent_id": agent_id,
                        "endpoint": endpoint,
                        "strategy": strategy,
                        "owner": owner,
                        "registered_at": registered_at,
                    })
            # Update cache on success
            self._cached_miners = miners
            self._cache_time = time.time()
            return miners

        except Exception as e:
            logger.error(f"Failed to read on-chain registry: {e}")
            return self._cached_miners  # Return last known state, not empty

    _cached_count: int = 0

    def get_miner_count(self) -> int:
        """Get total registered miners from chain. Returns cached value on failure."""
        if not self.enabled:
            return self._cached_count
        try:
            count = self.contract.functions.getActiveMinerCount().call()
            self._cached_count = count
            return count
        except Exception:
            return self._cached_count
