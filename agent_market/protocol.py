"""
Code Verification Protocol — Data contracts for the agent verification network.

Plain Pydantic models (no chain dependency). These define the exact data shape
that flows between validator agents and miner agents.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class CodeVerificationRequest(BaseModel):
    """Task sent from validator to miner agents."""

    code: str = Field(description="Source code to verify")
    intent: str = Field(description="Natural language description of what the code should do")
    language: str = Field(default="python", description="Programming language of the code")
    task_id: str = Field(default="", description="Unique identifier for this task")


class CodeVerificationResponse(BaseModel):
    """Audit report returned by a miner agent."""

    task_id: str = Field(default="", description="Task identifier")
    issues: List[dict] = Field(
        default=[],
        description="List of issues found. Each: {type, severity, line, description, suggestion}",
    )
    confidence: float = Field(default=0.0, description="Overall confidence score (0.0 to 1.0)")
    passed: bool = Field(default=True, description="Whether the code passes verification")
    suggestions: List[dict] = Field(
        default=[],
        description="Suggested fixes. Each: {line, original, fixed, explanation}",
    )
    processing_time: float = Field(default=0.0, description="Time taken to process (seconds)")
    agent_id: Optional[str] = Field(default=None, description="ERC-8004 agent identity")
