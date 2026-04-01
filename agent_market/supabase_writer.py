"""
Reliable Supabase writer with retry logic.

Replaces fire-and-forget background threads. Every write gets
max 3 attempts with exponential backoff. Failed writes are queued
for periodic retry.
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]  # seconds
RETRY_QUEUE_INTERVAL = 60  # seconds between retry queue flushes


class SupabaseWriter:
    """Async Supabase writer with retry and queue."""

    def __init__(self):
        self.enabled = bool(SUPABASE_URL and SUPABASE_KEY)
        self._retry_queue: list = []
        self._retry_task: Optional[asyncio.Task] = None

    async def write(self, table: str, data: dict, method: str = "POST") -> bool:
        """Write to a Supabase table with retry. Returns True on success."""
        if not self.enabled:
            return False

        for attempt in range(MAX_RETRIES):
            try:
                import httpx
                url = f"{SUPABASE_URL}/rest/v1/{table}"
                headers = {
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                }
                async with httpx.AsyncClient() as client:
                    if method == "POST":
                        resp = await client.post(url, json=data, headers=headers, timeout=10.0)
                    elif method == "PATCH":
                        resp = await client.patch(url, json=data, headers=headers, timeout=10.0)
                    else:
                        resp = await client.request(method, url, json=data, headers=headers, timeout=10.0)

                    if resp.status_code < 300:
                        return True
                    else:
                        logger.warning(f"Supabase write {table} attempt {attempt + 1} failed: {resp.status_code} {resp.text}")

            except Exception as e:
                logger.warning(f"Supabase write {table} attempt {attempt + 1} error: {e}")

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF[attempt])

        # All retries exhausted — queue for later
        self._retry_queue.append({
            "table": table,
            "data": data,
            "method": method,
            "queued_at": time.time(),
        })
        logger.error(f"Supabase write {table} failed after {MAX_RETRIES} attempts, queued for retry")
        return False

    async def upsert(self, table: str, data: dict, on_conflict: str = "") -> bool:
        """Upsert to a Supabase table (POST with Prefer: resolution=merge-duplicates)."""
        if not self.enabled:
            return False

        for attempt in range(MAX_RETRIES):
            try:
                import httpx
                url = f"{SUPABASE_URL}/rest/v1/{table}"
                headers = {
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal,resolution=merge-duplicates",
                }
                if on_conflict:
                    url += f"?on_conflict={on_conflict}"
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, json=data, headers=headers, timeout=10.0)
                    if resp.status_code < 300:
                        return True
                    else:
                        logger.warning(f"Supabase upsert {table} attempt {attempt + 1} failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Supabase upsert {table} attempt {attempt + 1} error: {e}")

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF[attempt])

        self._retry_queue.append({
            "table": table,
            "data": data,
            "method": "UPSERT",
            "queued_at": time.time(),
        })
        logger.error(f"Supabase upsert {table} failed after {MAX_RETRIES} attempts, queued")
        return False

    async def patch(self, path: str, data: dict) -> bool:
        """PATCH a specific Supabase path (e.g., 'api_keys?key_hash=eq.abc')."""
        if not self.enabled:
            return False

        for attempt in range(MAX_RETRIES):
            try:
                import httpx
                url = f"{SUPABASE_URL}/rest/v1/{path}"
                headers = {
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.patch(url, json=data, headers=headers, timeout=10.0)
                    if resp.status_code < 300:
                        return True
                    else:
                        logger.warning(f"Supabase patch {path} attempt {attempt + 1} failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Supabase patch {path} attempt {attempt + 1} error: {e}")

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF[attempt])

        logger.error(f"Supabase patch {path} failed after {MAX_RETRIES} attempts")
        return False

    async def _flush_retry_queue(self):
        """Process queued writes that previously failed."""
        if not self._retry_queue:
            return

        queue = self._retry_queue[:]
        self._retry_queue.clear()
        succeeded = 0
        failed = 0

        for item in queue:
            # Drop items older than 1 hour
            if time.time() - item["queued_at"] > 3600:
                logger.warning(f"Dropping stale retry item for {item['table']} (queued {int(time.time() - item['queued_at'])}s ago)")
                continue

            if item["method"] == "UPSERT":
                ok = await self.upsert(item["table"], item["data"])
            else:
                ok = await self.write(item["table"], item["data"], method=item["method"])

            if ok:
                succeeded += 1
            else:
                failed += 1

        if succeeded or failed:
            logger.info(f"Retry queue flush: {succeeded} succeeded, {failed} re-queued")

    async def start_retry_loop(self):
        """Start periodic retry queue flushing. Call from app startup."""
        async def _loop():
            while True:
                await asyncio.sleep(RETRY_QUEUE_INTERVAL)
                try:
                    await self._flush_retry_queue()
                except Exception as e:
                    logger.error(f"Retry queue flush error: {e}")

        self._retry_task = asyncio.create_task(_loop())


# Singleton instance
writer = SupabaseWriter()
