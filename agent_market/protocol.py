"""
Job Protocol — Data contracts for the Agent Labor Market.

Plain Pydantic models (no chain dependency). These define the exact data shape
that flows between manager agents and worker agents.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

# Max image size: ~10MB decoded (base64 is ~33% larger than raw bytes)
MAX_IMAGE_B64_LENGTH = 14_000_000


class JobRequest(BaseModel):
    """Job sent from manager to worker agents."""

    code: str = Field(default="", description="Source code to analyze")
    intent: str = Field(description="Natural language description of what the code should do")
    language: str = Field(default="python", description="Programming language of the code")
    task_id: str = Field(default="", description="Unique identifier for this job")
    image: str = Field(default="", description="Base64-encoded image data (for image-analysis tasks, max ~10MB)")
    task_type: str = Field(default="code-verification", description="'code-verification' | 'text-review' | 'image-analysis'")

    @field_validator("image")
    @classmethod
    def validate_image_size(cls, v: str) -> str:
        if v and len(v) > MAX_IMAGE_B64_LENGTH:
            raise ValueError(f"Image data exceeds maximum size ({len(v)} bytes, max {MAX_IMAGE_B64_LENGTH})")
        return v


class JobResponse(BaseModel):
    """Audit report returned by a worker agent."""

    task_id: str = Field(default="", description="Job identifier")
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


# Backward-compatible aliases
CodeVerificationRequest = JobRequest
CodeVerificationResponse = JobResponse
