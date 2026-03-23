"""
Miner Forward — The miner agent's entry point.

Receives a code verification request, runs the analysis pipeline,
and returns a structured audit report.
"""

import logging
import os
import time

from agent_market.protocol import CodeVerificationRequest, CodeVerificationResponse
from agent_market.miner.analyzer import analyze_code

logger = logging.getLogger(__name__)


async def forward(request: CodeVerificationRequest) -> CodeVerificationResponse:
    """
    Process a code verification request.

    Analyzes the code using AST parsing, pattern detection, and
    optionally LLM-based intent verification. Returns a structured report.
    """
    start_time = time.time()

    task_type = getattr(request, "task_type", "code-verification")
    valid_task_types = ("code-verification", "text-review", "image-analysis")
    if task_type not in valid_task_types:
        logger.warning(f"Unknown task_type '{task_type}', defaulting to code-verification")
        task_type = "code-verification"

    logger.info(f"Received task {request.task_id}: task_type={task_type}")

    try:
        use_llm = os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes")

        if task_type == "image-analysis":
            from agent_market.miner.image_analyzer import analyze_image
            result = analyze_image(
                image_data=getattr(request, "image", "") or request.code,
                intent=request.intent,
                use_llm=use_llm,
            )
        elif task_type == "text-review":
            from agent_market.miner.text_analyzer import analyze_text
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

        response = CodeVerificationResponse(
            task_id=request.task_id,
            issues=result["issues"],
            confidence=result["confidence"],
            passed=result["passed"],
            suggestions=result["suggestions"],
            processing_time=time.time() - start_time,
        )

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        response = CodeVerificationResponse(
            task_id=request.task_id,
            issues=[],
            confidence=0.0,
            passed=True,
            suggestions=[],
            processing_time=time.time() - start_time,
        )

    logger.info(
        f"Task {request.task_id} complete: "
        f"{len(response.issues)} issues found, "
        f"confidence={response.confidence:.2f}, "
        f"passed={response.passed}, "
        f"time={response.processing_time:.2f}s"
    )

    return response
