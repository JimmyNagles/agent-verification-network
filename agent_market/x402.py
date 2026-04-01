"""
x402 Payment Protocol Support

Implements the x402 HTTP payment protocol for the /verify endpoint.
When enabled, agents must pay ETH or USDC on Base for verification.

Two payment modes:
  1. x402 header — client includes PAYMENT-SIGNATURE header with signed payment proof
  2. Direct on-chain — client funds a job on AgenticCommerceV2 and passes the job_id

Protocol flow (x402):
  1. Client POSTs to /verify without payment header
  2. Server returns 402 with PAYMENT-REQUIRED header (base64-encoded JSON)
  3. Client signs a payment and retries with PAYMENT-SIGNATURE header
  4. Server validates the payment proof and proceeds with verification

Protocol flow (direct):
  1. Client calls AgenticCommerceV2.createJob() + fund() on-chain
  2. Client POSTs to /verify with {"job_id": 123} in the body
  3. Server verifies the job is funded on-chain and proceeds

Environment variables:
  X402_ENABLED      — "true" to require payments (default: disabled)
  PAYMENT_ADDRESS   — Recipient address (default: AgenticCommerceV2 contract)
  VERIFY_PRICE_ETH  — Price per verification in ETH (default: "0.0001")
  VERIFY_PRICE_USDC — Price per verification in USDC (default: "0.10")
  PAYMENT_TOKEN     — "eth" or "usdc" (default: "eth")
"""

import base64
import json
import os
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

# ── Configuration ────────────────────────────────────────────────

USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
COMMERCE_V2 = "0xA501a028F6C1d717009B65617540610aF25F02e7"
BASE_CHAIN_ID = 8453

DEFAULT_PRICE_ETH = "0.0001"
DEFAULT_PRICE_USDC = "0.10"


def _is_enabled() -> bool:
    return os.environ.get("X402_ENABLED", "").lower() == "true"


def _get_token() -> str:
    return os.environ.get("PAYMENT_TOKEN", "eth").lower()


def _get_price() -> str:
    token = _get_token()
    if token == "usdc":
        return os.environ.get("VERIFY_PRICE_USDC", DEFAULT_PRICE_USDC)
    return os.environ.get("VERIFY_PRICE_ETH", DEFAULT_PRICE_ETH)


def _get_recipient() -> str:
    return os.environ.get("PAYMENT_ADDRESS", COMMERCE_V2)


# ── Payment Requirements ─────────────────────────────────────────

def build_payment_requirements() -> dict:
    """Build the payment requirements object returned in 402 responses."""
    token = _get_token()

    if token == "usdc":
        return {
            "x402Version": 1,
            "schemes": ["exact"],
            "network": "base",
            "chainId": BASE_CHAIN_ID,
            "token": USDC_CONTRACT,
            "tokenSymbol": "USDC",
            "tokenDecimals": 6,
            "recipient": _get_recipient(),
            "amount": _get_price(),
            "description": "Task verification by the Agent Verification Network",
            "mimeType": "application/json",
            "resource": "/verify",
            "expiry": int(time.time()) + 3600,
            "commerce_contract": COMMERCE_V2,
        }
    else:
        return {
            "x402Version": 1,
            "schemes": ["exact"],
            "network": "base",
            "chainId": BASE_CHAIN_ID,
            "token": "0x0000000000000000000000000000000000000000",
            "tokenSymbol": "ETH",
            "tokenDecimals": 18,
            "recipient": _get_recipient(),
            "amount": _get_price(),
            "description": "Task verification by the Agent Verification Network",
            "mimeType": "application/json",
            "resource": "/verify",
            "expiry": int(time.time()) + 3600,
            "commerce_contract": COMMERCE_V2,
            "alternative": "You can also fund a job directly on AgenticCommerceV2 and pass job_id in the request body.",
        }


def encode_payment_requirements(requirements: dict) -> str:
    """Base64-encode the payment requirements for the PAYMENT-REQUIRED header."""
    return base64.b64encode(json.dumps(requirements).encode()).decode()


# ── Payment Validation ───────────────────────────────────────────

def decode_payment_signature(header_value: str) -> Optional[dict]:
    """Decode a base64-encoded PAYMENT-SIGNATURE header into a dict."""
    try:
        decoded = base64.b64decode(header_value)
        return json.loads(decoded)
    except Exception:
        return None


def validate_payment_proof(proof: dict) -> tuple[bool, str]:
    """
    Validate a payment proof from the PAYMENT-SIGNATURE header.

    Verifies the transaction ON-CHAIN — no fake payments accepted.
    The proof must contain a txHash that we verify on Base Mainnet:
      - Transaction exists and is confirmed
      - Payment was sent to the correct recipient
      - Amount meets the minimum price
    """
    required_fields = ["scheme", "network", "payload"]
    for field in required_fields:
        if field not in proof:
            return False, f"Missing required field: {field}"

    if proof.get("scheme") != "exact":
        return False, f"Unsupported scheme: {proof.get('scheme')}"

    if proof.get("network") != "base":
        return False, f"Unsupported network: {proof.get('network')}"

    payload = proof.get("payload", {})
    if not isinstance(payload, dict):
        return False, "Invalid payload format"

    # Must have a tx hash — we verify on-chain
    tx_hash = payload.get("txHash") or payload.get("tx_hash")
    if not tx_hash:
        return False, "Missing txHash — submit a real transaction on Base and include the hash"

    # Replay prevention — check if this tx hash was already consumed
    try:
        from agent_market.keys import _supabase_get, _supabase_post
        existing = _supabase_get(f"consumed_tx_hashes?tx_hash=eq.{tx_hash}&select=tx_hash")
        if existing:
            return False, f"Transaction {tx_hash} has already been used for payment. Each tx can only be used once."
    except Exception:
        return False, "Unable to verify tx hash uniqueness (Supabase unavailable). Try again."

    # Verify the transaction on-chain
    try:
        from web3 import Web3
        rpc_url = os.environ.get("BASE_RPC_URL", "")
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        # Get the transaction receipt
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is None:
            return False, f"Transaction {tx_hash} not found on Base"

        if receipt.status != 1:
            return False, f"Transaction {tx_hash} failed (reverted)"

        # Get the transaction details
        tx = w3.eth.get_transaction(tx_hash)

        # Verify the payment — supports ETH direct transfers AND ERC-20 token transfers
        expected_recipient = _get_recipient().lower()
        tx_to = (tx.to or "").lower()

        # Check if this is an ETH transfer to the recipient
        if tx.value > 0 and tx_to == expected_recipient:
            min_price = float(os.environ.get("VERIFY_PRICE_ETH", "0.0001"))
            min_wei = int(min_price * 1e18)
            if tx.value < min_wei:
                return False, f"Payment too low: sent {w3.from_wei(tx.value, 'ether')} ETH, minimum is {min_price} ETH"
            # Mark tx hash as consumed (replay prevention) — reject if recording fails
            try:
                _supabase_post("consumed_tx_hashes", {"tx_hash": tx_hash})
            except Exception:
                return False, "Payment verified but failed to record tx hash. Try again."
            return True, f"ETH payment verified on-chain: tx {tx_hash}"

        # Check if this is an ERC-20 token transfer (AVNC or other)
        # ERC-20 transfers go TO the token contract, not the recipient directly
        avnc_address = "0x6f1F2C3DB90DFc2956A7Ba1CB8bFf31420B4cc8F".lower()
        if tx_to == avnc_address or tx_to == expected_recipient:
            # Check transfer events in the receipt for ERC-20 Transfer
            transfer_topic = w3.keccak(text="Transfer(address,address,uint256)")
            min_price_eth = float(os.environ.get("VERIFY_PRICE_ETH", "0.0001"))
            min_price_wei = int(min_price_eth * 1e18)
            for log_entry in receipt.logs:
                if log_entry.topics and log_entry.topics[0] == transfer_topic:
                    if len(log_entry.topics) >= 3:
                        to_addr = "0x" + log_entry.topics[2].hex()[-40:]
                        if to_addr.lower() == expected_recipient:
                            # Verify amount — data field contains the uint256 amount
                            amount = int(log_entry.data.hex(), 16) if log_entry.data else 0
                            if amount < min_price_wei:
                                return False, f"AVNC payment too low: sent {amount / 1e18:.6f}, minimum is {min_price_eth}"
                            # Mark tx hash as consumed (replay prevention) — reject if recording fails
                            try:
                                _supabase_post("consumed_tx_hashes", {"tx_hash": tx_hash})
                            except Exception:
                                return False, "Payment verified but failed to record tx hash. Try again."
                            return True, f"AVNC token payment verified on-chain: tx {tx_hash}"

        # If we got here, payment didn't match
        return False, f"Transaction {tx_hash} does not contain a valid payment to {expected_recipient}"

    except Exception as e:
        return False, f"On-chain verification failed: {e}"


def verify_onchain_job(job_id: int, commerce_client) -> tuple[bool, str]:
    """
    Verify that a job is funded on-chain (direct payment mode).

    Client can fund a job on AgenticCommerceV2 directly and pass
    the job_id. We verify the job exists and is in Funded state.
    """
    if not commerce_client or not commerce_client.enabled:
        return False, "Commerce not enabled"

    try:
        job = commerce_client.contract.functions.getJob(job_id).call()
        state = job[6]  # State enum: 0=Open, 1=Funded, 2=Submitted, 3=Completed

        if state == 0:
            return False, f"Job {job_id} is not funded yet. Call fund() on AgenticCommerceV2."
        elif state == 1:
            return True, f"Job {job_id} is funded and ready for verification."
        elif state >= 2:
            return False, f"Job {job_id} is already submitted or completed."
        else:
            return False, f"Job {job_id} has unexpected state: {state}"

    except Exception as e:
        return False, f"Failed to verify job {job_id}: {e}"


# ── Middleware / Handler ─────────────────────────────────────────

async def check_x402_payment(request: Request) -> Optional[JSONResponse]:
    """
    Check for x402 payment on an incoming request.

    Returns:
      - None if x402 is disabled or payment is valid (proceed with request)
      - JSONResponse(402) if payment is required but missing/invalid
    """
    if not _is_enabled():
        return None

    # Note: API key validation is handled in server.py before this function is called.
    # This function only handles x402 payment headers.

    # Check for payment header (support both naming conventions)
    payment_header = (
        request.headers.get("PAYMENT-SIGNATURE")
        or request.headers.get("X-PAYMENT")
        or request.headers.get("X-Payment-Proof")
        or request.headers.get("payment-signature")
        or request.headers.get("x-payment")
        or request.headers.get("x-payment-proof")
    )

    if not payment_header:
        # No payment — return 402 with requirements
        requirements = build_payment_requirements()
        encoded = encode_payment_requirements(requirements)
        return JSONResponse(
            status_code=402,
            content={
                "error": "Payment Required",
                "message": "This endpoint requires payment. Include a PAYMENT-SIGNATURE header or fund a job on AgenticCommerceV2 and pass job_id in the body.",
                "paymentRequirements": requirements,
            },
            headers={
                "PAYMENT-REQUIRED": encoded,
            },
        )

    # Payment header present — validate it
    proof = decode_payment_signature(payment_header)
    if proof is None:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Invalid Payment",
                "message": "Could not decode PAYMENT-SIGNATURE header. Expected base64-encoded JSON.",
            },
        )

    valid, reason = validate_payment_proof(proof)
    if not valid:
        requirements = build_payment_requirements()
        encoded = encode_payment_requirements(requirements)
        return JSONResponse(
            status_code=402,
            content={
                "error": "Payment Rejected",
                "message": reason,
                "paymentRequirements": requirements,
            },
            headers={
                "PAYMENT-REQUIRED": encoded,
            },
        )

    # Payment valid — proceed
    return None


# ── Pricing Info ─────────────────────────────────────────────────

def get_pricing_info() -> dict:
    """Return current pricing configuration."""
    token = _get_token()
    return {
        "x402_enabled": _is_enabled(),
        "verify_price": _get_price(),
        "currency": "USDC" if token == "usdc" else "ETH",
        "network": "base",
        "chain_id": BASE_CHAIN_ID,
        "token_contract": USDC_CONTRACT if token == "usdc" else "0x0000000000000000000000000000000000000000",
        "recipient": _get_recipient(),
        "commerce_contract": COMMERCE_V2,
        "protocol": "x402",
        "protocol_version": 1,
        "payment_modes": [
            "x402 header — include PAYMENT-SIGNATURE in your HTTP request",
            "Direct on-chain — fund a job on AgenticCommerceV2 and pass job_id",
        ],
    }
