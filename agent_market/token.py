"""
Protocol Credits (AVNC) — token client for the Agent Verification Network.

Token: 0x1cb00aF12987274C5505F6fccF2B610268D81D03 on Base Mainnet
Symbol: AVNC (Agent Verification Credits)
Faucet: 20 AVNC per claim, 1 day cooldown

Agents use AVNC to pay for verification tasks on AgenticCommerceV2.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEPLOYED_PATH = Path(__file__).parent.parent / "contracts" / "token_deployed.json"


class TokenClient:
    """Interact with ProtocolCredits on Base Mainnet."""

    def __init__(self):
        self.enabled = False
        self.w3 = None
        self.contract = None
        self.account = None
        self.address = None

        if not DEPLOYED_PATH.exists():
            logger.info("No token_deployed.json — token features disabled")
            return

        try:
            from web3 import Web3

            with open(DEPLOYED_PATH) as f:
                info = json.load(f)

            rpc_url = os.environ.get("BASE_RPC_URL", info.get("rpc", "https://mainnet.base.org"))
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            if not self.w3.is_connected():
                logger.warning("Cannot connect to RPC — token disabled")
                return

            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(info["address"]),
                abi=info["abi"],
            )
            self.address = info["address"]
            self.chain_id = 8453 if "mainnet" in info.get("chain", "") else 84532
            self.enabled = True

            # Set up account if private key available
            private_key = os.environ.get("PRIVATE_KEY")
            if private_key:
                self.account = self.w3.eth.account.from_key(private_key)

            logger.info(f"Token enabled: {info['address']} ({info.get('symbol', 'AVNC')})")

        except Exception as e:
            logger.warning(f"Failed to initialize token client: {e}")

    def get_balance(self, address: str) -> int:
        """Get AVNC balance for an address (in wei)."""
        if not self.enabled:
            return 0
        try:
            return self.contract.functions.balanceOf(
                self.w3.to_checksum_address(address)
            ).call()
        except Exception:
            return 0

    def claim_faucet(self, recipient: str) -> Optional[dict]:
        """
        Claim faucet credits for an address.
        The manager calls this on behalf of the agent.
        """
        if not self.enabled or not self.account:
            return None

        try:
            # Transfer faucet amount from our supply to the recipient
            faucet_amount = self.contract.functions.faucetAmount().call()

            tx = self.contract.functions.transfer(
                self.w3.to_checksum_address(recipient),
                faucet_amount,
            ).build_transaction({
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.chain_id,
            })

            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            amount_human = faucet_amount / 1e18

            result = {
                "tx_hash": tx_hash.hex(),
                "recipient": recipient,
                "amount": amount_human,
                "symbol": "AVNC",
                "token": self.address,
                "chain": "base-mainnet",
            }
            logger.info(f"Faucet: sent {amount_human} AVNC to {recipient}, tx={tx_hash.hex()}")
            return result

        except Exception as e:
            logger.error(f"Faucet claim failed: {e}")
            return None

    def transfer(self, recipient: str, amount_wei: int) -> Optional[dict]:
        """Transfer AVNC tokens to a recipient address."""
        if not self.enabled or not self.account:
            return None

        try:
            tx = self.contract.functions.transfer(
                self.w3.to_checksum_address(recipient),
                amount_wei,
            ).build_transaction({
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.chain_id,
            })

            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            return {
                "tx_hash": tx_hash.hex(),
                "amount": amount_wei / 1e18,
                "recipient": recipient,
                "status": "confirmed" if receipt.status == 1 else "failed",
            }
        except Exception as e:
            logger.error(f"Token transfer failed: {e}")
            return None

    def get_info(self) -> dict:
        """Get token info."""
        if not self.enabled:
            return {"enabled": False}

        try:
            total = self.contract.functions.totalSupply().call()
            faucet_amount = self.contract.functions.faucetAmount().call()
            return {
                "enabled": True,
                "address": self.address,
                "symbol": "AVNC",
                "name": "Agent Verification Credits",
                "decimals": 18,
                "total_supply": total / 1e18,
                "faucet_amount": faucet_amount / 1e18,
                "chain": "base-mainnet",
                "explorer": f"https://basescan.org/address/{self.address}",
            }
        except Exception:
            return {"enabled": True, "address": self.address}
