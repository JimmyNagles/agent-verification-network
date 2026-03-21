"""
Filecoin Storage — stores verification reports on decentralized storage.

Uses Lighthouse Storage to upload JSON reports to IPFS/Filecoin.
Reports become permanent, tamper-proof, and retrievable by CID.
When LIGHTHOUSE_API_KEY is not set, storage is disabled and all
calls are no-ops so the system works without any storage dependency.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

LIGHTHOUSE_UPLOAD_URL = "https://node.lighthouse.storage/api/v0/add"
LIGHTHOUSE_GATEWAY = "https://gateway.lighthouse.storage/ipfs"


async def store_on_filecoin(data: dict, filename: str = "report.json") -> Optional[dict]:
    """
    Upload JSON data to Filecoin via Lighthouse Storage.

    Returns {"cid": "Qm...", "url": "https://gateway.lighthouse.storage/ipfs/Qm..."}
    or None if storage is disabled or fails.
    """
    api_key = os.environ.get("LIGHTHOUSE_API_KEY")
    if not api_key:
        logger.debug("LIGHTHOUSE_API_KEY not set — Filecoin storage disabled")
        return None

    try:
        import urllib.request
        import urllib.error

        json_bytes = json.dumps(data, indent=2).encode("utf-8")

        # Build multipart form data manually (no extra deps)
        boundary = "----FilecoinUploadBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/json\r\n"
            f"\r\n"
        ).encode("utf-8") + json_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            LIGHTHOUSE_UPLOAD_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "AgentVerificationNetwork/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        cid = result.get("Hash", result.get("cid", ""))
        if not cid:
            logger.warning(f"Filecoin upload returned no CID: {result}")
            return None

        storage_result = {
            "cid": cid,
            "url": f"{LIGHTHOUSE_GATEWAY}/{cid}",
            "filename": filename,
            "size": result.get("Size", len(json_bytes)),
            "storage": "filecoin/ipfs",
            "provider": "lighthouse",
        }

        logger.info(f"Stored on Filecoin: {cid} ({filename})")
        return storage_result

    except Exception as e:
        logger.warning(f"Filecoin storage failed: {e}")
        return None


def get_filecoin_url(cid: str) -> str:
    """Get the gateway URL for a Filecoin CID."""
    return f"{LIGHTHOUSE_GATEWAY}/{cid}"
