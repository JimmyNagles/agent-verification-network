"""
ERC-8004 Integration — Identity and Reputation on the official registries.

Identity Registry: 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432 (Base Mainnet)
Reputation Registry: 0x8004BAa17C55a88189AE136b182e5fdA19dE9b63 (Base Mainnet)

Our agent is registered as Agent ID 34655.
"""

import hashlib
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
REPUTATION_REGISTRY = "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63"
OUR_AGENT_ID = 34655
BASE_MAINNET_RPC = "https://mainnet.base.org"
CHAIN_ID = 8453

# Minimal ABIs for the functions we need
REPUTATION_ABI = [
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "value", "type": "int128"},
            {"name": "valueDecimals", "type": "uint8"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
            {"name": "endpoint", "type": "string"},
            {"name": "feedbackURI", "type": "string"},
            {"name": "feedbackHash", "type": "bytes32"},
        ],
        "name": "giveFeedback",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddresses", "type": "address[]"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
        ],
        "name": "getSummary",
        "outputs": [
            {"name": "count", "type": "uint64"},
            {"name": "summaryValue", "type": "int128"},
            {"name": "summaryValueDecimals", "type": "uint8"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "getClients",
        "outputs": [{"name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]

IDENTITY_ABI = [
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class ERC8004Client:
    """Interact with the official ERC-8004 registries on Base Mainnet."""

    def __init__(self):
        self.enabled = False
        self.w3 = None
        self.identity = None
        self.reputation = None
        self.account = None

        private_key = os.environ.get("PRIVATE_KEY")
        if not private_key:
            logger.info("PRIVATE_KEY not set — ERC-8004 reputation publishing disabled")
            return

        try:
            from web3 import Web3

            self.w3 = Web3(Web3.HTTPProvider(BASE_MAINNET_RPC))
            if not self.w3.is_connected():
                logger.warning("Cannot connect to Base Mainnet — ERC-8004 disabled")
                return

            self.identity = self.w3.eth.contract(
                address=self.w3.to_checksum_address(IDENTITY_REGISTRY),
                abi=IDENTITY_ABI,
            )
            self.reputation = self.w3.eth.contract(
                address=self.w3.to_checksum_address(REPUTATION_REGISTRY),
                abi=REPUTATION_ABI,
            )
            self.account = self.w3.eth.account.from_key(private_key)
            self.enabled = True
            logger.info(f"ERC-8004 enabled: agent_id={OUR_AGENT_ID}, wallet={self.account.address}")

        except Exception as e:
            logger.warning(f"Failed to initialize ERC-8004 client: {e}")

    def publish_reputation(
        self,
        agent_id: int,
        score: float,
        task_type: str = "code-verification",
        task_id: str = "",
        endpoint: str = "",
    ) -> Optional[dict]:
        """
        Publish a miner's reputation score to the official ERC-8004 Reputation Registry.

        Args:
            agent_id: The ERC-8004 agent ID being scored (the miner's agent NFT ID)
            score: Quality score 0.0 to 1.0
            task_type: Category tag (e.g., "code-verification")
            task_id: Specific task identifier
            endpoint: The miner's service endpoint
        """
        if not self.enabled:
            return None

        try:
            # Convert score to int128 with 2 decimals (e.g., 0.95 → 9500)
            value = int(score * 10000)
            value_decimals = 2

            # Create feedback hash from task details
            feedback_data = json.dumps({"task_id": task_id, "score": score}).encode()
            feedback_hash = hashlib.sha256(feedback_data).digest()

            tx = self.reputation.functions.giveFeedback(
                agent_id,           # agentId being rated
                value,              # score value
                value_decimals,     # decimal places
                task_type,          # tag1: category
                task_id,            # tag2: task identifier
                endpoint,           # service endpoint
                "",                 # feedbackURI (could link to detailed report)
                feedback_hash,      # integrity hash
            ).build_transaction({
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gasPrice": self.w3.eth.gas_price,
                "chainId": CHAIN_ID,
            })

            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            result = {
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.blockNumber,
                "agent_id": agent_id,
                "score": score,
                "registry": REPUTATION_REGISTRY,
                "chain": "base-mainnet",
            }
            logger.info(f"ERC-8004 reputation published: agent={agent_id}, score={score}, tx={tx_hash.hex()}")
            return result

        except Exception as e:
            logger.error(f"ERC-8004 reputation publish failed: {e}")
            return None

    def get_agent_reputation(self, agent_id: int, tag1: str = "") -> Optional[dict]:
        """Read an agent's reputation summary from the official registry."""
        if not self.enabled:
            return None

        try:
            # Get all clients who gave feedback
            clients = self.reputation.functions.getClients(agent_id).call()
            if not clients:
                return {"agent_id": agent_id, "count": 0, "score": 0}

            count, value, decimals = self.reputation.functions.getSummary(
                agent_id, clients, tag1, ""
            ).call()

            score = value / (10 ** decimals) if decimals > 0 else value

            return {
                "agent_id": agent_id,
                "count": count,
                "score": float(score),
                "clients": len(clients),
            }

        except Exception as e:
            logger.error(f"Failed to read ERC-8004 reputation: {e}")
            return None

    def verify_agent_identity(self, agent_id: int) -> Optional[dict]:
        """Verify an agent exists on the official Identity Registry."""
        if not self.enabled:
            return None

        try:
            owner = self.identity.functions.ownerOf(agent_id).call()
            uri = self.identity.functions.tokenURI(agent_id).call()

            return {
                "agent_id": agent_id,
                "owner": owner,
                "uri": uri[:200] if len(uri) > 200 else uri,
                "verified": True,
            }

        except Exception as e:
            return {"agent_id": agent_id, "verified": False, "error": str(e)}
