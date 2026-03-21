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
COMMERCE_V2 = "0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1"
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

    Checks:
      - Required fields present (scheme, network, payload)
      - Scheme is "exact"
      - Network is "base"
      - Payment targets the correct recipient
      - Transaction signature exists

    For full on-chain verification, a facilitator service would
    confirm the transaction is settled on Base.
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

    # Check that the payment targets the correct recipient
    expected_recipient = _get_recipient().lower()
    proof_recipient = payload.get("recipient", "").lower()
    if proof_recipient and proof_recipient != expected_recipient:
        return False, "Payment recipient mismatch"

    # Accept both ETH and USDC
    token = _get_token()
    proof_token = payload.get("token", "").lower()
    if token == "usdc" and proof_token and proof_token != USDC_CONTRACT.lower():
        return False, "Invalid token — USDC required"

    # Check signature or tx hash exists
    if not payload.get("signature") and not payload.get("txHash"):
        return False, "Missing transaction signature or tx hash"

    return True, "Payment accepted"


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

    # API key bypass — allows internal services (GitHub Action, etc.) to skip payment
    api_key = os.environ.get("VERIFY_API_KEY", "")
    if api_key:
        request_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("x-api-key")
            or request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if request_key == api_key:
            return None  # Authorized, skip payment

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
