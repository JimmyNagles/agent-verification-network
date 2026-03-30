"""
Text Analyzer — analyzes text for quality, accuracy, and intent compliance.

This is the second task type for the Agent Verification Network.
Code verification is task type #1. Text review is task type #2.

The protocol doesn't care what the task is — it uses the same contracts,
same scoring, same fee split. Only the analysis logic changes.
"""

import logging
import os
import re
from typing import List, Dict

logger = logging.getLogger(__name__)


def analyze_text(text: str, intent: str, use_llm: bool = False) -> dict:
    """
    Analyze text for quality issues against the stated intent.

    Returns same format as code analyzer:
    {
        "issues": [...],
        "confidence": float,
        "passed": bool,
        "suggestions": [...]
    }
    """
    all_issues = []

    # Pass 1: Basic quality checks (pattern-based)
    quality_issues = check_text_quality(text)
    all_issues.extend(quality_issues)

    # Pass 2: Intent matching
    intent_issues = check_intent_match(text, intent)
    all_issues.extend(intent_issues)

    # Pass 3: LLM-based deep analysis (if available)
    if use_llm:
        llm_issues = llm_text_analysis(text, intent)
        if llm_issues is not None:
            all_issues.extend(llm_issues)

    # Calculate confidence
    confidence = 0.7
    if len(all_issues) > 0:
        confidence += min(0.25, len(all_issues) * 0.05)
    if use_llm:
        confidence += 0.05
    confidence = min(1.0, confidence)

    critical_or_high = [i for i in all_issues if i.get("severity") in ("critical", "high")]
    passed = len(critical_or_high) == 0

    suggestions = [
        {"line": i.get("line", 0), "description": i.get("suggestion", i.get("description", "")), "severity": i.get("severity", "medium")}
        for i in all_issues if i.get("suggestion") or i.get("description")
    ]

    return {
        "issues": all_issues,
        "confidence": confidence,
        "passed": passed,
        "suggestions": suggestions,
        "task_type": "text-review",
    }


def check_text_quality(text: str) -> List[Dict]:
    """Pattern-based text quality checks."""
    issues = []
    lines = text.split("\n")

    # Check for very short text
    if len(text.strip()) < 10:
        issues.append({
            "type": "quality",
            "severity": "high",
            "line": 0,
            "description": "Text is too short to be meaningful",
            "suggestion": "Provide more detailed text",
        })

    # Check for ALL CAPS
    words = text.split()
    caps_words = [w for w in words if w.isupper() and len(w) > 2]
    if len(caps_words) > len(words) * 0.3 and len(words) > 5:
        issues.append({
            "type": "tone",
            "severity": "medium",
            "line": 0,
            "description": "Excessive use of ALL CAPS — may appear aggressive or unprofessional",
            "suggestion": "Use standard capitalization for a professional tone",
        })

    # Check for repeated words
    for i, line in enumerate(lines, 1):
        line_words = line.lower().split()
        for j in range(len(line_words) - 1):
            if line_words[j] == line_words[j + 1] and len(line_words[j]) > 2:
                issues.append({
                    "type": "grammar",
                    "severity": "low",
                    "line": i,
                    "description": f"Repeated word: '{line_words[j]} {line_words[j]}'",
                    "suggestion": f"Remove the duplicate '{line_words[j]}'",
                })
                break

    # Check for common errors
    error_patterns = [
        (r'\bi\.e\b(?!\.)', "grammar", "low", "'i.e' should be 'i.e.' with a period"),
        (r'\be\.g\b(?!\.)', "grammar", "low", "'e.g' should be 'e.g.' with a period"),
        (r'\byour\s+welcome\b', "grammar", "medium", "'your welcome' should be 'you're welcome'"),
        (r'\btheir\s+is\b', "grammar", "medium", "'their is' should be 'there is'"),
        (r'\bcould\s+of\b', "grammar", "medium", "'could of' should be 'could have'"),
        (r'\bshould\s+of\b', "grammar", "medium", "'should of' should be 'should have'"),
        (r'\bwould\s+of\b', "grammar", "medium", "'would of' should be 'would have'"),
        (r'\balot\b', "grammar", "low", "'alot' should be 'a lot'"),
        (r'\bdefinately\b', "grammar", "low", "'definately' should be 'definitely'"),
        (r'\brecieve\b', "grammar", "low", "'recieve' should be 'receive'"),
        (r'\boccured\b', "grammar", "low", "'occured' should be 'occurred'"),
        (r'\bguarantee\w*\s+\d{2,3}%', "accuracy", "high", "Percentage guarantees should be verified — may be misleading"),
        (r'\balways\b.*\bnever\b|\bnever\b.*\balways\b', "accuracy", "medium", "Absolute claims ('always'/'never') are often inaccurate"),
        (r'\b(free|unlimited)\b.*\b(forever|lifetime|always)\b', "accuracy", "high", "Claims of unlimited/forever free access should be verified"),
    ]

    for pattern, issue_type, severity, description in error_patterns:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                issues.append({
                    "type": issue_type,
                    "severity": severity,
                    "line": i,
                    "description": description,
                    "suggestion": description,
                })

    # Check for placeholder text
    placeholders = ["lorem ipsum", "todo", "fixme", "xxx", "placeholder", "insert here", "tbd"]
    for i, line in enumerate(lines, 1):
        for ph in placeholders:
            if ph in line.lower():
                issues.append({
                    "type": "incomplete",
                    "severity": "critical",
                    "line": i,
                    "description": f"Placeholder text found: '{ph}'",
                    "suggestion": "Replace placeholder with actual content",
                })

    return issues


def check_intent_match(text: str, intent: str) -> List[Dict]:
    """Check if the text matches the stated intent."""
    issues = []
    intent_lower = intent.lower()
    text_lower = text.lower()

    # Check if intent mentions professional/formal but text is casual
    if any(w in intent_lower for w in ["professional", "formal", "enterprise", "business"]):
        casual_markers = ["lol", "btw", "gonna", "wanna", "gotta", "kinda", "idk", "tbh", "ngl"]
        for marker in casual_markers:
            if marker in text_lower:
                issues.append({
                    "type": "tone_mismatch",
                    "severity": "high",
                    "line": 0,
                    "description": f"Intent requires professional tone but text contains casual language ('{marker}')",
                    "suggestion": "Use formal language consistent with the intended audience",
                })

    # Check if intent mentions accuracy but text has unverified claims
    if any(w in intent_lower for w in ["accurate", "factual", "truthful", "verified"]):
        if re.search(r'\b(probably|maybe|might|possibly|could be)\b', text_lower):
            issues.append({
                "type": "accuracy",
                "severity": "medium",
                "line": 0,
                "description": "Intent requires accuracy but text contains hedging language (probably/maybe/might)",
                "suggestion": "Use definitive statements or cite sources for claims",
            })

    # Check length expectations
    if "brief" in intent_lower or "concise" in intent_lower or "short" in intent_lower:
        if len(text.split()) > 200:
            issues.append({
                "type": "intent_mismatch",
                "severity": "medium",
                "line": 0,
                "description": f"Intent says '{intent[:50]}' but text is {len(text.split())} words — not concise",
                "suggestion": "Shorten the text to match the intent",
            })

    if "detailed" in intent_lower or "comprehensive" in intent_lower or "thorough" in intent_lower:
        if len(text.split()) < 50:
            issues.append({
                "type": "intent_mismatch",
                "severity": "high",
                "line": 0,
                "description": f"Intent requires detailed content but text is only {len(text.split())} words",
                "suggestion": "Expand the text with more detail as the intent requires",
            })

    return issues


def llm_text_analysis(text: str, intent: str) -> list:
    """Use LLM for deep text analysis."""
    try:
        from agent_market.worker.analyzer import LLMClient
        client = LLMClient()

        system_prompt = """You are a text quality reviewer. Analyze the text against the stated intent.
Check for: grammar errors, factual accuracy, tone appropriateness, completeness, clarity.
Return a JSON array of issues found. Each issue has:
- "type": "grammar" | "accuracy" | "tone" | "clarity" | "completeness" | "intent_mismatch"
- "severity": "critical" | "high" | "medium" | "low"
- "line": line number (0 if applies to whole text)
- "description": what's wrong
- "suggestion": how to fix it
Return [] if no issues found. Return ONLY the JSON array, nothing else."""

        user_prompt = f"Intent: {intent}\n\nText to review:\n{text}"

        response = client.chat(system_prompt, user_prompt)
        if response:
            import json
            # Try to parse JSON from the response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            issues = json.loads(response)
            if isinstance(issues, list):
                return issues

    except Exception as e:
        logger.warning(f"LLM text analysis failed: {e}")

    return None
