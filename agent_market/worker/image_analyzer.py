"""
Image Analyzer — analyzes images for quality, format, and intent compliance.

This is the third task type for the Agent Verification Network.
Code verification is task type #1. Text review is task type #2.
Image validation is task type #3.

The protocol doesn't care what the task is — it uses the same contracts,
same scoring, same fee split. Only the analysis logic changes.

Uses Venice AI's vision model (qwen3-vl-235b-a22b) for semantic analysis
when LLM is enabled. Falls back to heuristic checks (stdlib only, no Pillow).
"""

import base64
import json
import logging
import os
import re
import struct
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Format Detection ────────────────────────────────────────────────────────

# Magic bytes for common image formats
MAGIC_BYTES = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
    "gif87a": b"GIF87a",
    "gif89a": b"GIF89a",
    "webp_riff": b"RIFF",
    "bmp": b"BM",
}


def detect_format(data: bytes) -> Optional[str]:
    """Detect image format from magic bytes."""
    if data[:8] == MAGIC_BYTES["png"]:
        return "png"
    if data[:3] == MAGIC_BYTES["jpeg"]:
        return "jpeg"
    if data[:6] in (MAGIC_BYTES["gif87a"], MAGIC_BYTES["gif89a"]):
        return "gif"
    if data[:4] == MAGIC_BYTES["webp_riff"] and len(data) > 11 and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == MAGIC_BYTES["bmp"]:
        return "bmp"
    return None


def get_png_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Extract width, height from PNG IHDR chunk."""
    if len(data) < 24:
        return None
    try:
        width = struct.unpack(">I", data[16:20])[0]
        height = struct.unpack(">I", data[20:24])[0]
        return (width, height)
    except struct.error:
        return None


def get_jpeg_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Extract width, height from JPEG SOF marker."""
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        # SOF0, SOF1, SOF2 markers
        if marker in (0xC0, 0xC1, 0xC2):
            height = struct.unpack(">H", data[i + 5:i + 7])[0]
            width = struct.unpack(">H", data[i + 7:i + 9])[0]
            return (width, height)
        # Skip marker segment
        if marker == 0xD9:  # EOI
            break
        if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01):
            i += 2
            continue
        if i + 3 < len(data):
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg_len
        else:
            break
    return None


# ─── Main Analyzer ────────────────────────────────────────────────────────────

def analyze_image(image_data: str, intent: str, use_llm: bool = False) -> dict:
    """
    Analyze an image for quality, format, and intent compliance.

    Args:
        image_data: Base64-encoded image string, optionally with data URI prefix
        intent: Natural language description of what the image should be
        use_llm: If True, use Venice vision model for semantic analysis

    Returns same format as code/text analyzers:
    {
        "issues": [...],
        "confidence": float,
        "passed": bool,
        "suggestions": [...],
        "job_type": "image-analysis"
    }
    """
    all_issues = []

    # Normalize: strip data URI prefix if present
    image_b64, mime_type = _normalize_image_data(image_data)

    # Try to decode base64
    try:
        raw_bytes = base64.b64decode(image_b64)
    except Exception:
        all_issues.append({
            "type": "format",
            "severity": "critical",
            "line": 0,
            "description": "Invalid base64 encoding — image data cannot be decoded",
            "suggestion": "Provide valid base64-encoded image data",
        })
        return _build_response(all_issues, use_llm)

    # Pass 1: Format validation
    format_issues = check_format(raw_bytes)
    all_issues.extend(format_issues)

    # Pass 2: Size and dimension checks
    size_issues = check_size_and_dimensions(raw_bytes, intent)
    all_issues.extend(size_issues)

    # Pass 3: Content checks (blank detection, truncation)
    content_issues = check_content(raw_bytes)
    all_issues.extend(content_issues)

    # Pass 4: Intent matching
    intent_issues = check_intent_match(raw_bytes, intent)
    all_issues.extend(intent_issues)

    # Pass 5: LLM vision analysis (Venice)
    if use_llm:
        llm_issues = llm_image_analysis(image_b64, intent, mime_type)
        if llm_issues is not None:
            all_issues.extend(llm_issues)

    return _build_response(all_issues, use_llm)


def _normalize_image_data(image_data: str) -> Tuple[str, str]:
    """Strip data URI prefix, return (base64_string, mime_type)."""
    mime_type = "image/jpeg"
    b64 = image_data.strip()

    match = re.match(r"data:(image/\w+);base64,(.+)", b64, re.DOTALL)
    if match:
        mime_type = match.group(1)
        b64 = match.group(2)

    return b64, mime_type


def _build_response(issues: List[Dict], llm_used: bool = False) -> dict:
    """Build the standard response dict."""
    confidence = 0.7
    if len(issues) > 0:
        confidence += min(0.25, len(issues) * 0.05)
    if llm_used:
        confidence += 0.05
    confidence = min(1.0, confidence)

    critical_or_high = [i for i in issues if i.get("severity") in ("critical", "high")]
    passed = len(critical_or_high) == 0

    suggestions = [
        {
            "line": i.get("line", 0),
            "description": i.get("suggestion", i.get("description", "")),
            "severity": i.get("severity", "medium"),
        }
        for i in issues if i.get("suggestion") or i.get("description")
    ]

    return {
        "issues": issues,
        "confidence": confidence,
        "passed": passed,
        "suggestions": suggestions,
        "job_type": "image-analysis",
    }


# ─── Pass 1: Format Validation ───────────────────────────────────────────────

def check_format(data: bytes) -> List[Dict]:
    """Check image format via magic bytes."""
    issues = []
    fmt = detect_format(data)

    if fmt is None:
        issues.append({
            "type": "format",
            "severity": "critical",
            "line": 0,
            "description": "Unrecognized image format — file does not match any known image type (PNG, JPEG, GIF, WebP, BMP)",
            "suggestion": "Provide a valid image file in a standard format",
        })

    return issues


# ─── Pass 2: Size & Dimensions ───────────────────────────────────────────────

def check_size_and_dimensions(data: bytes, intent: str) -> List[Dict]:
    """Check file size and image dimensions."""
    issues = []
    size = len(data)

    # Too small — likely blank or trivial
    if size < 1024:
        issues.append({
            "type": "quality",
            "severity": "high",
            "line": 0,
            "description": f"Image file is very small ({size} bytes) — likely blank or trivial content",
            "suggestion": "Provide a meaningful image with actual content",
        })

    # Too large
    if size > 10 * 1024 * 1024:
        issues.append({
            "type": "quality",
            "severity": "medium",
            "line": 0,
            "description": f"Image file is very large ({size // (1024*1024)} MB) — may cause processing issues",
            "suggestion": "Compress or resize the image before submission",
        })

    # Check dimensions
    fmt = detect_format(data)
    dims = None
    if fmt == "png":
        dims = get_png_dimensions(data)
    elif fmt == "jpeg":
        dims = get_jpeg_dimensions(data)

    if dims:
        width, height = dims
        # Tiny image
        if width < 10 or height < 10:
            issues.append({
                "type": "quality",
                "severity": "high",
                "line": 0,
                "description": f"Image dimensions are too small ({width}x{height}) — insufficient for meaningful content",
                "suggestion": "Provide an image with reasonable dimensions (at least 50x50 pixels)",
            })

        # Extreme aspect ratio
        if dims[0] > 0 and dims[1] > 0:
            ratio = max(width, height) / min(width, height)
            if ratio > 10:
                issues.append({
                    "type": "quality",
                    "severity": "medium",
                    "line": 0,
                    "description": f"Extreme aspect ratio ({width}x{height}, ratio {ratio:.1f}:1) — may indicate a corrupted or non-standard image",
                    "suggestion": "Check if the image dimensions are correct",
                })

    return issues


# ─── Pass 3: Content Checks ──────────────────────────────────────────────────

def check_content(data: bytes) -> List[Dict]:
    """Check for blank images and truncation."""
    issues = []
    fmt = detect_format(data)

    # Blank/uniform detection
    fmt = detect_format(data)

    if fmt == "png":
        # For PNG: a solid-color image compresses extremely well.
        # Check if compressed data is suspiciously small relative to dimensions.
        dims = get_png_dimensions(data)
        if dims:
            w, h = dims
            expected_raw = w * h * 3  # RGB bytes uncompressed
            # Find IDAT chunk(s) total size
            idat_size = 0
            pos = 8  # after PNG signature
            while pos < len(data) - 8:
                try:
                    chunk_len = struct.unpack(">I", data[pos:pos+4])[0]
                    chunk_type = data[pos+4:pos+8]
                    if chunk_type == b"IDAT":
                        idat_size += chunk_len
                    pos += 12 + chunk_len  # length + type + data + crc
                except (struct.error, IndexError):
                    break
            # A solid-color image compresses to near-zero. If IDAT is < 1% of
            # expected raw size and image is non-trivial, flag it.
            if expected_raw > 100 and idat_size > 0 and idat_size < expected_raw * 0.01:
                issues.append({
                    "type": "content",
                    "severity": "high",
                    "line": 0,
                    "description": "Image appears to be blank or uniform — compressed data is suspiciously small relative to dimensions",
                    "suggestion": "Provide an image with actual visual content",
                })
    else:
        # For non-PNG: sample raw bytes at intervals
        if len(data) > 100:
            sample_points = [len(data) * i // 20 for i in range(1, 20)]
            sampled = [data[p] for p in sample_points if p < len(data)]
            if sampled and all(b == sampled[0] for b in sampled):
                issues.append({
                    "type": "content",
                    "severity": "high",
                    "line": 0,
                    "description": "Image appears to be blank or uniform — all sampled bytes are identical",
                    "suggestion": "Provide an image with actual visual content",
                })

    # Truncation detection
    if fmt == "jpeg":
        if not data.endswith(b"\xff\xd9"):
            issues.append({
                "type": "format",
                "severity": "high",
                "line": 0,
                "description": "JPEG file appears truncated — missing end-of-image marker (FFD9)",
                "suggestion": "Re-upload the complete image file",
            })

    if fmt == "png":
        # Check for IEND chunk
        if b"IEND" not in data[-20:]:
            issues.append({
                "type": "format",
                "severity": "high",
                "line": 0,
                "description": "PNG file appears truncated — missing IEND chunk",
                "suggestion": "Re-upload the complete image file",
            })

    return issues


# ─── Pass 4: Intent Matching ─────────────────────────────────────────────────

def check_intent_match(data: bytes, intent: str) -> List[Dict]:
    """Check if image properties match the stated intent."""
    issues = []
    intent_lower = intent.lower()
    size = len(data)
    fmt = detect_format(data)

    dims = None
    if fmt == "png":
        dims = get_png_dimensions(data)
    elif fmt == "jpeg":
        dims = get_jpeg_dimensions(data)

    # High-res intent vs tiny image
    highres_keywords = ["high-resolution", "high resolution", "hi-res", "hires", "detailed", "print", "4k", "8k"]
    if any(kw in intent_lower for kw in highres_keywords):
        if dims and (dims[0] < 200 or dims[1] < 200):
            issues.append({
                "type": "intent_mismatch",
                "severity": "high",
                "line": 0,
                "description": f"Intent requires high resolution but image is only {dims[0]}x{dims[1]} pixels",
                "suggestion": "Provide a higher resolution image matching the intent",
            })
        if size < 10000:
            issues.append({
                "type": "intent_mismatch",
                "severity": "medium",
                "line": 0,
                "description": f"Intent requires high resolution but file is only {size} bytes — unusually small",
                "suggestion": "Check if the image was compressed too aggressively",
            })

    # Thumbnail/icon intent vs huge image
    small_keywords = ["thumbnail", "icon", "favicon", "avatar", "small"]
    if any(kw in intent_lower for kw in small_keywords):
        if size > 5 * 1024 * 1024:
            issues.append({
                "type": "intent_mismatch",
                "severity": "medium",
                "line": 0,
                "description": f"Intent suggests a small image ({intent[:40]}) but file is {size // (1024*1024)} MB",
                "suggestion": "Resize and compress the image to match the intended use",
            })
        if dims and (dims[0] > 128 or dims[1] > 128):
            issues.append({
                "type": "intent_mismatch",
                "severity": "medium",
                "line": 0,
                "description": f"Intent suggests a small image but dimensions are {dims[0]}x{dims[1]}",
                "suggestion": "Resize the image to appropriate dimensions for a thumbnail/icon",
            })

    # Photo intent vs non-photo format
    photo_keywords = ["photograph", "photo", "picture", "snapshot"]
    if any(kw in intent_lower for kw in photo_keywords):
        if fmt and fmt not in ("jpeg", "png", "webp"):
            issues.append({
                "type": "intent_mismatch",
                "severity": "medium",
                "line": 0,
                "description": f"Intent suggests a photograph but image is in {fmt.upper()} format — unusual for photos",
                "suggestion": "Use JPEG or PNG format for photographs",
            })

    # Logo intent — should be reasonably sized, not huge
    if "logo" in intent_lower:
        if size > 5 * 1024 * 1024:
            issues.append({
                "type": "intent_mismatch",
                "severity": "low",
                "line": 0,
                "description": f"Logo file is {size // (1024*1024)} MB — logos are typically much smaller",
                "suggestion": "Optimize the logo file size",
            })

    return issues


# ─── Pass 5: LLM Vision Analysis ─────────────────────────────────────────────

def llm_image_analysis(image_b64: str, intent: str, mime_type: str = "image/jpeg") -> Optional[List[Dict]]:
    """Use Venice AI vision model for semantic image analysis."""
    try:
        from agent_market.worker.analyzer import LLMClient
        client = LLMClient()

        system_prompt = """You are an image verification agent for the Agent Verification Network.
Analyze the submitted image against its stated intent. Check for:
- Content mismatch: Does the image content match what was described?
- Quality issues: Is the image blurry, pixelated, or poorly composed?
- Missing elements: Are expected elements absent from the image?
- Inappropriate content: Does the image contain anything harmful or unsafe?
- Misleading visuals: Could the image be misleading in context?

Return a JSON array of issues found. Each issue must have:
- "type": "content_mismatch" | "quality" | "missing_element" | "safety" | "misleading"
- "severity": "critical" | "high" | "medium" | "low"
- "line": 0
- "description": what's wrong
- "suggestion": how to fix it
Return [] if no issues found. Return ONLY the JSON array, nothing else."""

        user_prompt = f"Stated intent: {intent}\n\nAnalyze the image below against this intent."

        response = client.chat_vision(system_prompt, user_prompt, image_b64, mime_type)
        if response:
            response = response.strip()
            # Strip markdown code fences if present
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            issues = json.loads(response)
            if isinstance(issues, list):
                return issues

    except Exception as e:
        logger.warning(f"LLM image analysis failed: {e}")

    return None
