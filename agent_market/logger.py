"""
Agent Event Logger — writes structured events to agent_log.json.

Every significant action (registration, verification, scoring) is logged
so the hackathon submission has a real execution trail.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

LOG_PATH = Path(__file__).parent.parent / "agent_log.json"


def _load_log() -> dict:
    if LOG_PATH.exists():
        with open(LOG_PATH, "r") as f:
            return json.load(f)
    return {
        "agent": "Agent Verification Network",
        "version": "1.0.0",
        "events": [],
    }


def _save_log(log: dict):
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def log_event(
    event_type: str,
    agent_role: str,
    agent_id: str,
    details: Optional[dict] = None,
):
    """Append a structured event to agent_log.json."""
    log = _load_log()
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": event_type,
        "agent_role": agent_role,
        "agent_id": agent_id,
    }
    if details:
        event["details"] = details
    log["events"].append(event)
    _save_log(log)
    return event
