"""
Worker Forward — The worker agent's entry point.

Receives a job request, runs the analysis pipeline,
and returns a structured audit report.
"""

import logging
import os
import time

from agent_market.protocol import JobRequest, JobResponse
from agent_market.worker.analyzer import analyze_code

logger = logging.getLogger(__name__)


async def forward(request: JobRequest) -> JobResponse:
    """
    Process a code verification request.

    Analyzes the code using AST parsing, pattern detection, and
    optionally LLM-based intent verification. Returns a structured report.
    """
    start_time = time.time()

    job_type = getattr(request, "job_type", "code-verification")
    valid_job_types = ("code-verification", "text-review", "image-analysis")
    if job_type not in valid_job_types:
        logger.warning(f"Unknown job_type '{job_type}', defaulting to code-verification")
        job_type = "code-verification"

    logger.info(f"Received task {request.job_id}: job_type={job_type}")

    try:
        use_llm = os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes")

        if job_type == "image-analysis":
            from agent_market.worker.image_analyzer import analyze_image
            result = analyze_image(
                image_data=getattr(request, "image", "") or request.code,
                intent=request.intent,
                use_llm=use_llm,
            )
        elif job_type == "text-review":
            from agent_market.worker.text_analyzer import analyze_text
            result = analyze_text(
                text=getattr(request, "text", "") or request.code,
                intent=request.intent,
                use_llm=use_llm,
            )
        else:
            result = analyze_code(
                code=request.code,
                intent=request.intent,
                language=request.language,
                use_llm=use_llm,
            )

        response = JobResponse(
            job_id=request.job_id,
            issues=result["issues"],
            confidence=result["confidence"],
            passed=result["passed"],
            suggestions=result["suggestions"],
            processing_time=time.time() - start_time,
        )

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        response = JobResponse(
            job_id=request.job_id,
            issues=[{"type": "error", "severity": "critical", "line": 0, "description": f"Analysis failed: {str(e)}"}],
            confidence=0.0,
            passed=False,  # Fail-closed: errors should not approve code
            suggestions=[],
            processing_time=time.time() - start_time,
        )

    logger.info(
        f"Task {request.job_id} complete: "
        f"{len(response.issues)} issues found, "
        f"confidence={response.confidence:.2f}, "
        f"passed={response.passed}, "
        f"time={response.processing_time:.2f}s"
    )

    return response
