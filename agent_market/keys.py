"""
API Key Manager — issue and validate client API keys via Supabase.

Each manager manages their own keys. This is NOT part of the protocol —
it's a manager-level convenience layer. The protocol only knows about
wallets, jobs, and on-chain payments. API keys are for clients who want
to use the network without touching the blockchain.

Storage: Supabase (hosted Postgres). Survives redeploys.

Env vars:
  SUPABASE_URL      — Supabase project URL
  SUPABASE_KEY      — Supabase anon key
  VERIFY_API_KEY    — Internal bypass key (for GitHub Action etc.)
"""

import hashlib
import json
import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zdxisjihyfybnzwurjto.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpkeGlzamloeWZ5Ym56d3VyanRvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQxMjA3NDEsImV4cCI6MjA4OTY5Njc0MX0.xdTOG6ILZ6bReo8Kj8XQn3xwSK2rt1s8UggJCYl1o54")
FREE_CREDITS = 20


def _supabase_request(method: str, path: str, data: dict = None) -> Optional[dict]:
    """Make a request to Supabase REST API."""
    import urllib.request
    import urllib.error

    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    body = json.dumps(data).encode("utf-8") if data else None

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Supabase {method} {path} failed: {e.code} {error_body}")
        return None
    except Exception as e:
        logger.error(f"Supabase request failed: {e}")
        return None


def _supabase_get(path: str) -> Optional[list]:
    """GET from Supabase REST API."""
    return _supabase_request("GET", path)


def _supabase_post(path: str, data: dict) -> Optional[list]:
    """POST to Supabase REST API."""
    return _supabase_request("POST", path, data)


def _supabase_patch(path: str, data: dict) -> Optional[list]:
    """PATCH to Supabase REST API."""
    return _supabase_request("PATCH", path, data)


class KeyManager:
    """Issue and validate API keys for clients. Backed by Supabase."""

    def __init__(self):
        self.enabled = bool(SUPABASE_URL and SUPABASE_KEY)
        if self.enabled:
            logger.info(f"KeyManager initialized with Supabase: {SUPABASE_URL}")
        else:
            logger.warning("KeyManager disabled — no SUPABASE_URL/KEY")

    def _hash_key(self, key: str) -> str:
        """Hash an API key for storage. Never store raw keys."""
        return hashlib.sha256(key.encode()).hexdigest()

    def create_key(self, agent_name: str, wallet_address: str = None) -> Optional[dict]:
        """
        Create a new API key for a client.
        Returns the raw key (shown once, never stored) and metadata.
        """
        if not self.enabled:
            return None

        raw_key = f"avnk-{secrets.token_hex(16)}"
        key_hash = self._hash_key(raw_key)
        key_prefix = raw_key[:12] + "..."

        result = _supabase_post("api_keys", {
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "agent_name": agent_name,
            "wallet_address": wallet_address,
            "credits_remaining": FREE_CREDITS,
            "total_used": 0,
            "is_active": True,
        })

        if result:
            logger.info(f"API key created: {key_prefix} for {agent_name}")
            return {
                "api_key": raw_key,
                "key_prefix": key_prefix,
                "agent_name": agent_name,
                "credits": FREE_CREDITS,
                "note": "Save this key — it is shown only once.",
            }

        return None

    def validate_key(self, raw_key: str) -> Optional[dict]:
        """
        Validate an API key. Returns key info if valid, None if invalid.
        """
        # Check internal bypass key first
        internal_key = os.environ.get("VERIFY_API_KEY", "")
        if internal_key and raw_key == internal_key:
            return {
                "valid": True,
                "type": "internal",
                "credits_remaining": 999999,
                "agent_name": "internal-service",
            }

        if not self.enabled:
            return None

        key_hash = self._hash_key(raw_key)
        result = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&is_active=eq.true&select=agent_name,credits_remaining,total_used")

        if not result or len(result) == 0:
            return None

        row = result[0]
        return {
            "valid": True,
            "type": "client",
            "agent_name": row["agent_name"],
            "credits_remaining": row["credits_remaining"],
            "total_used": row["total_used"],
        }

    def use_credit(self, raw_key: str, endpoint: str = "/verify", task_id: str = None) -> bool:
        """
        Use one credit from an API key. Returns True if credit was available.
        """
        # Internal keys have unlimited credits
        internal_key = os.environ.get("VERIFY_API_KEY", "")
        if internal_key and raw_key == internal_key:
            return True

        if not self.enabled:
            return False

        key_hash = self._hash_key(raw_key)

        # Check credits
        result = _supabase_get(f"api_keys?key_hash=eq.{key_hash}&is_active=eq.true&select=credits_remaining")
        if not result or len(result) == 0 or result[0]["credits_remaining"] <= 0:
            return False

        # Decrement credit
        _supabase_patch(f"api_keys?key_hash=eq.{key_hash}", {
            "credits_remaining": result[0]["credits_remaining"] - 1,
            "total_used": result[0].get("total_used", 0) + 1 if "total_used" in result[0] else 1,
            "last_used_at": "now()",
        })

        # Log usage
        _supabase_post("usage_log", {
            "key_hash": key_hash,
            "endpoint": endpoint,
            "task_id": task_id,
        })

        return True

    def is_name_taken(self, agent_name: str) -> bool:
        """Check if an agent name is already registered."""
        if not self.enabled:
            return False

        result = _supabase_get(f"api_keys?agent_name=eq.{agent_name}&is_active=eq.true&select=id")
        return result is not None and len(result) > 0

    def get_stats(self) -> dict:
        """Get overall key statistics."""
        if not self.enabled:
            return {"total_keys": 0, "active_keys": 0, "total_verifications": 0}

        try:
            keys = _supabase_get("api_keys?select=is_active,total_used")
            if not keys:
                return {"total_keys": 0, "active_keys": 0, "total_verifications": 0}

            total = len(keys)
            active = len([k for k in keys if k.get("is_active")])
            usage = sum(k.get("total_used", 0) for k in keys)

            return {
                "total_keys": total,
                "active_keys": active,
                "total_verifications": usage,
            }
        except Exception:
            return {"total_keys": 0, "active_keys": 0, "total_verifications": 0}
