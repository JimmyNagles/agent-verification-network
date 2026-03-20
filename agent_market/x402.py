"""
x402 Payment Protocol Support

Implements the x402 HTTP payment protocol for the /verify endpoint.
When enabled, agents must pay USDC on Base for code verification.

Protocol flow:
  1. Client POSTs to /verify without payment header
  2. Server returns 402 with PAYMENT-REQUIRED header (base64-encoded JSON)
  3. Client signs a payment transaction and retries with PAYMENT-SIGNATURE header
  4. Server validates the payment proof and proceeds with verification

Environment variables:
  X402_ENABLED      — "true" to require payments (default: disabled)
  PAYMENT_ADDRESS   — Recipient address for USDC payments
  VERIFY_PRICE      — Price per verification in USDC (default: "0.01")
"""

import base64
import json
import os
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

# ── Configuration ────────────────────────────────────────────────

# USDC on Base
USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_CHAIN_ID = 8453

DEFAULT_PRICE = "0.01"
DEFAULT_PAYMENT_ADDRESS = "0x0000000000000000000000000000000000000000"


def _is_enabled() -> bool:
    return os.environ.get("X402_ENABLED", "").lower() == "true"


def _get_price() -> str:
    return os.environ.get("VERIFY_PRICE", DEFAULT_PRICE)


def _get_recipient() -> str:
    return os.environ.get("PAYMENT_ADDRESS", DEFAULT_PAYMENT_ADDRESS)


# ── Payment Requirements ─────────────────────────────────────────

def build_payment_requirements() -> dict:
    """Build the payment requirements object returned in 402 responses."""
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
        "description": "Code verification by the Agent Verification Network",
        "mimeType": "application/json",
        "resource": "/verify",
        "expiry": int(time.time()) + 3600,  # 1 hour
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

    In production this would verify:
      - The transaction signature is valid
      - The payment was sent to the correct recipient
      - The amount meets the required price
      - The token is USDC on Base
      - The transaction is confirmed on-chain

    For now, we do structural validation — checking that the proof
    contains the required fields and matches our requirements.
    Full on-chain verification would use a facilitator service.
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

    # Check that the payment targets the correct recipient and token
    expected_recipient = _get_recipient().lower()
    proof_recipient = payload.get("recipient", "").lower()
    if proof_recipient and proof_recipient != expected_recipient:
        return False, "Payment recipient mismatch"

    proof_token = payload.get("token", "").lower()
    if proof_token and proof_token != USDC_CONTRACT.lower():
        return False, "Invalid token — only USDC on Base accepted"

    # Check signature exists
    if not payload.get("signature"):
        return False, "Missing transaction signature"

    return True, "Payment accepted"


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
                "message": "This endpoint requires x402 payment. Include a PAYMENT-SIGNATURE header.",
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
    return {
        "x402_enabled": _is_enabled(),
        "verify_price": _get_price(),
        "currency": "USDC",
        "network": "base",
        "chain_id": BASE_CHAIN_ID,
        "token_contract": USDC_CONTRACT,
        "recipient": _get_recipient(),
        "protocol": "x402",
        "protocol_version": 1,
    }
