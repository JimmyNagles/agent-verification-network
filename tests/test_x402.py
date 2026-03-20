"""
Tests for x402 payment protocol support.

Validates that:
1. x402 is disabled by default — /verify works without payment
2. When enabled, /verify returns 402 without payment header
3. Valid payment proofs are accepted
4. Invalid payment proofs are rejected
5. /pricing endpoint returns correct configuration
"""

import base64
import json
import os
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_market.api.server import app
from agent_market.x402 import (
    build_payment_requirements,
    decode_payment_signature,
    encode_payment_requirements,
    validate_payment_proof,
    get_pricing_info,
    USDC_CONTRACT,
    BASE_CHAIN_ID,
)


client = TestClient(app)

SAMPLE_CODE = "def add(a, b):\n    return a + b"
SAMPLE_INTENT = "Add two numbers"
VERIFY_PAYLOAD = {"code": SAMPLE_CODE, "intent": SAMPLE_INTENT, "language": "python"}

RECIPIENT = "0x1234567890abcdef1234567890abcdef12345678"


def _make_valid_proof(recipient=RECIPIENT) -> str:
    """Build a valid base64-encoded payment proof."""
    proof = {
        "scheme": "exact",
        "network": "base",
        "payload": {
            "recipient": recipient,
            "token": USDC_CONTRACT,
            "amount": "0.01",
            "signature": "0xdeadbeef",
        },
    }
    return base64.b64encode(json.dumps(proof).encode()).decode()


# ── Disabled by Default ──────────────────────────────────────────

class TestX402Disabled:
    def test_verify_works_without_payment(self):
        """When X402_ENABLED is not set, /verify should work normally."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X402_ENABLED", None)
            resp = client.post("/verify", json=VERIFY_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()
            assert "task_id" in data
            assert "passed" in data

    def test_pricing_shows_disabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X402_ENABLED", None)
            resp = client.get("/pricing")
            assert resp.status_code == 200
            data = resp.json()
            assert data["x402_enabled"] is False


# ── Enabled — No Payment ────────────────────────────────────────

class TestX402EnabledNoPayment:
    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_returns_402_without_payment(self):
        resp = client.post("/verify", json=VERIFY_PAYLOAD)
        assert resp.status_code == 402
        data = resp.json()
        assert data["error"] == "Payment Required"
        assert "paymentRequirements" in data

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_402_includes_header(self):
        resp = client.post("/verify", json=VERIFY_PAYLOAD)
        assert "payment-required" in resp.headers

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_402_requirements_fields(self):
        resp = client.post("/verify", json=VERIFY_PAYLOAD)
        reqs = resp.json()["paymentRequirements"]
        assert reqs["network"] == "base"
        assert reqs["chainId"] == BASE_CHAIN_ID
        assert reqs["token"] == USDC_CONTRACT
        assert reqs["recipient"] == RECIPIENT
        assert reqs["amount"] == "0.01"


# ── Enabled — Valid Payment ──────────────────────────────────────

class TestX402ValidPayment:
    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_valid_payment_proceeds(self):
        proof = _make_valid_proof()
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"PAYMENT-SIGNATURE": proof},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_x_payment_header_also_works(self):
        proof = _make_valid_proof()
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"X-PAYMENT": proof},
        )
        assert resp.status_code == 200

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_x_payment_proof_header_also_works(self):
        proof = _make_valid_proof()
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"X-Payment-Proof": proof},
        )
        assert resp.status_code == 200


# ── Enabled — Invalid Payment ───────────────────────────────────

class TestX402InvalidPayment:
    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_garbage_header_rejected(self):
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"PAYMENT-SIGNATURE": "not-valid-base64!!!"},
        )
        assert resp.status_code == 402
        assert "Invalid Payment" in resp.json()["error"]

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_wrong_scheme_rejected(self):
        proof = {
            "scheme": "streaming",
            "network": "base",
            "payload": {"signature": "0xabc"},
        }
        encoded = base64.b64encode(json.dumps(proof).encode()).decode()
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"PAYMENT-SIGNATURE": encoded},
        )
        assert resp.status_code == 402

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_wrong_recipient_rejected(self):
        proof = _make_valid_proof(recipient="0xdeaddeaddeaddeaddeaddeaddeaddeaddeaddead")
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"PAYMENT-SIGNATURE": proof},
        )
        assert resp.status_code == 402

    @patch.dict(os.environ, {"X402_ENABLED": "true", "PAYMENT_ADDRESS": RECIPIENT})
    def test_missing_signature_rejected(self):
        proof = {
            "scheme": "exact",
            "network": "base",
            "payload": {"recipient": RECIPIENT, "token": USDC_CONTRACT},
        }
        encoded = base64.b64encode(json.dumps(proof).encode()).decode()
        resp = client.post(
            "/verify",
            json=VERIFY_PAYLOAD,
            headers={"PAYMENT-SIGNATURE": encoded},
        )
        assert resp.status_code == 402


# ── Unit Tests for x402 Module ───────────────────────────────────

class TestX402Module:
    def test_build_payment_requirements(self):
        with patch.dict(os.environ, {"PAYMENT_ADDRESS": RECIPIENT, "VERIFY_PRICE": "0.05"}):
            reqs = build_payment_requirements()
            assert reqs["recipient"] == RECIPIENT
            assert reqs["amount"] == "0.05"
            assert reqs["x402Version"] == 1

    def test_encode_decode_roundtrip(self):
        reqs = build_payment_requirements()
        encoded = encode_payment_requirements(reqs)
        decoded = json.loads(base64.b64decode(encoded))
        assert decoded == reqs

    def test_decode_invalid_returns_none(self):
        assert decode_payment_signature("!!!invalid!!!") is None

    def test_validate_missing_fields(self):
        valid, reason = validate_payment_proof({})
        assert not valid
        assert "Missing" in reason

    def test_pricing_info(self):
        with patch.dict(os.environ, {"X402_ENABLED": "true", "VERIFY_PRICE": "0.50"}):
            info = get_pricing_info()
            assert info["x402_enabled"] is True
            assert info["verify_price"] == "0.50"
            assert info["currency"] == "USDC"
