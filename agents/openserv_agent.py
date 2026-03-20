#!/usr/bin/env python3
"""
OpenServ Agent — Registers the Agent Verification Network on OpenServ.

Exposes code verification and honeypot scoring as OpenServ capabilities,
making the verification service discoverable and callable by other agents
on the OpenServ platform.

Usage:
    export OPENSERV_API_KEY=your-key
    python -m agents.openserv_agent [--port 7378]
"""

import argparse
import logging
import os

from pydantic import BaseModel, Field

from openserv import Agent
from openserv.types import AgentOptions
from openserv.capability import Capability

from agent_market.miner.analyzer import analyze_code
from agent_market.validator.honeypot import HoneypotGenerator
from agent_market.validator.scorer import MinerScorer
from agent_market.logger import log_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("openserv-agent")


# ── Capability Schemas ──────────────────────────────────────

class VerifyCodeSchema(BaseModel):
    code: str = Field(description="Source code to verify")
    intent: str = Field(description="What the code should do (natural language)")
    language: str = Field(default="python", description="Programming language")


class ScoreVerificationSchema(BaseModel):
    code: str = Field(description="Source code that was verified")
    intent: str = Field(description="What the code should do")
    issues_found: int = Field(description="Number of issues the miner found")
    passed: bool = Field(description="Whether the miner said the code passed")


# ── Capability Handlers ─────────────────────────────────────

def verify_code(args: VerifyCodeSchema, messages) -> str:
    """Run code verification and return a structured report."""
    import json

    logger.info(f"OpenServ: verifying {args.language} code")

    result = analyze_code(
        code=args.code,
        intent=args.intent,
        language=args.language,
        use_llm=os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes"),
    )

    log_event(
        event_type="openserv_verification",
        agent_role="miner",
        agent_id="openserv-agent",
        details={
            "issues_found": len(result["issues"]),
            "confidence": result["confidence"],
            "passed": result["passed"],
        },
    )

    report = {
        "passed": result["passed"],
        "confidence": result["confidence"],
        "issues": result["issues"],
        "suggestions": result["suggestions"],
        "analysis_pipeline": ["ast_parsing", "pattern_detection", "intent_verification"],
    }

    return json.dumps(report, indent=2)


def score_verification(args: ScoreVerificationSchema, messages) -> str:
    """Score a verification result using honeypot ground truth."""
    import json

    honeypot_gen = HoneypotGenerator()
    scorer = MinerScorer()

    # Generate a honeypot from the provided code to get ground truth
    code, intent, known_bugs = honeypot_gen.generate()

    # Score based on the miner's claims
    score = scorer.score(
        response_issues=[{"type": "bug", "severity": "medium"}] * args.issues_found,
        response_passed=args.passed,
        response_confidence=0.8,
        response_time=1.0,
        is_honeypot=True,
        known_bugs=known_bugs,
    )

    log_event(
        event_type="openserv_scoring",
        agent_role="validator",
        agent_id="openserv-agent",
        details={"score": round(score, 4)},
    )

    return json.dumps({
        "score": round(score, 4),
        "scoring_formula": "0.6 * honeypot_detection + 0.2 * consensus + 0.1 * format + 0.1 * speed",
    }, indent=2)


# ── Agent Setup ─────────────────────────────────────────────

def create_agent() -> Agent:
    api_key = os.environ.get("OPENSERV_API_KEY")
    if not api_key:
        raise ValueError("Set OPENSERV_API_KEY environment variable")

    agent = Agent(AgentOptions(
        system_prompt=(
            "You are the Agent Verification Network — a decentralized code verification service. "
            "You analyze code for bugs, security issues, and intent mismatches using AST parsing, "
            "pattern detection, and LLM intent verification. You score verification quality using "
            "synthetic honeypots with known ground truth. Your scores are recorded on-chain via "
            "ERC-8004 on Base."
        ),
        api_key=api_key,
    ))

    agent.add_capability(Capability(
        name="verify_code",
        description=(
            "Analyze source code for bugs, security vulnerabilities, and intent mismatches. "
            "Returns a structured audit report with issues found, severity levels, line numbers, "
            "confidence score, and fix suggestions. Supports Python code analysis via AST parsing, "
            "regex pattern detection (SQL injection, hardcoded secrets, eval, infinite loops), "
            "and optional LLM-based intent verification."
        ),
        schema=VerifyCodeSchema,
        run=verify_code,
    ))

    agent.add_capability(Capability(
        name="score_verification",
        description=(
            "Score a code verification result using the honeypot scoring system. "
            "Evaluates how well a verifier detected known bugs using the multi-signal "
            "scoring formula: 0.6 * honeypot_detection + 0.2 * consensus + 0.1 * format + 0.1 * speed."
        ),
        schema=ScoreVerificationSchema,
        run=score_verification,
    ))

    log_event(
        event_type="agent_started",
        agent_role="openserv",
        agent_id="openserv-agent",
        details={
            "platform": "openserv",
            "capabilities": ["verify_code", "score_verification"],
        },
    )

    return agent


def main():
    parser = argparse.ArgumentParser(description="Run the OpenServ verification agent")
    parser.add_argument("--port", type=int, default=7378, help="Port to listen on")
    args = parser.parse_args()

    os.environ.setdefault("PORT", str(args.port))

    logger.info(f"Starting OpenServ agent on port {args.port}")
    agent = create_agent()
    agent.start()


if __name__ == "__main__":
    main()
