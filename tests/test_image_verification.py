"""
Tests for image verification — task type #3.

Tests the image analyzer, image spot_check generator, and scorer integration.
"""

import base64
import struct
import zlib

import pytest


# ─── Helper: build valid PNGs for testing ────────────────────────────────────

def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def make_valid_png(width: int = 100, height: int = 80) -> bytes:
    """Create a valid PNG with varied pixel data."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _make_png_chunk(b"IHDR", ihdr_data)
    raw_data = b""
    for y in range(height):
        raw_data += b"\x00"  # filter byte
        for x in range(width):
            r = (x * 7 + y * 13) % 256
            g = (x * 11 + y * 3) % 256
            b = (x * 5 + y * 17) % 256
            raw_data += bytes([r, g, b])
    compressed = zlib.compress(raw_data)
    idat = _make_png_chunk(b"IDAT", compressed)
    iend = _make_png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def make_solid_png(width: int = 50, height: int = 50, rgb: tuple = (0, 0, 0)) -> bytes:
    """Create a solid-color PNG."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _make_png_chunk(b"IHDR", ihdr_data)
    row = bytes(rgb) * width
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00" + row
    compressed = zlib.compress(raw_data)
    idat = _make_png_chunk(b"IDAT", compressed)
    iend = _make_png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


# ─── Image Analyzer Tests ───────────────────────────────────────────────────

class TestImageAnalyzer:

    def test_detects_invalid_base64(self):
        """Garbage string should produce a critical format issue."""
        from agent_market.worker.image_analyzer import analyze_image

        result = analyze_image("not-valid-base64!!!", "A product photo")
        assert result["passed"] is False
        assert any(i["type"] == "format" and i["severity"] == "critical" for i in result["issues"])
        assert result["job_type"] == "image-analysis"

    def test_detects_blank_image(self):
        """Solid-color PNG should be flagged as blank/uniform."""
        from agent_market.worker.image_analyzer import analyze_image

        blank_png = make_solid_png(50, 50, (0, 0, 0))
        b64 = base64.b64encode(blank_png).decode()
        result = analyze_image(b64, "Product photograph showing the item")
        assert any(i["type"] == "content" for i in result["issues"])

    def test_detects_truncated_jpeg(self):
        """Truncated JPEG (no EOI) should be flagged."""
        from agent_market.worker.image_analyzer import analyze_image

        # Minimal JPEG header without EOI
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00\x10" + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 100
        b64 = base64.b64encode(jpeg_bytes).decode()
        result = analyze_image(b64, "High-resolution logo")
        format_issues = [i for i in result["issues"] if i["type"] == "format"]
        assert len(format_issues) > 0

    def test_detects_tiny_image(self):
        """1x1 PNG with detailed-content intent should flag size mismatch."""
        from agent_market.worker.image_analyzer import analyze_image

        tiny_png = make_solid_png(1, 1, (128, 128, 128))
        b64 = base64.b64encode(tiny_png).decode()
        result = analyze_image(b64, "Detailed infographic explaining product features")
        assert result["passed"] is False
        assert any(i["type"] == "quality" for i in result["issues"])

    def test_detects_unrecognized_format(self):
        """Random bytes should be flagged as unrecognized format."""
        from agent_market.worker.image_analyzer import analyze_image

        garbage = base64.b64encode(b"This is not an image file").decode()
        result = analyze_image(garbage, "Professional photo")
        assert any(i["type"] == "format" and i["severity"] == "critical" for i in result["issues"])

    def test_accepts_data_uri_prefix(self):
        """data:image/png;base64,... prefix should be handled correctly."""
        from agent_market.worker.image_analyzer import analyze_image

        valid_png = make_valid_png(100, 80)
        b64 = base64.b64encode(valid_png).decode()
        data_uri = f"data:image/png;base64,{b64}"
        result = analyze_image(data_uri, "A simple test image")
        assert result["job_type"] == "image-analysis"
        # Should not flag format issues — it's a valid PNG
        format_issues = [i for i in result["issues"] if i["type"] == "format" and i["severity"] == "critical"]
        assert len(format_issues) == 0

    def test_valid_image_passes(self):
        """A reasonable PNG with matching intent should pass."""
        from agent_market.worker.image_analyzer import analyze_image

        valid_png = make_valid_png(200, 150)
        b64 = base64.b64encode(valid_png).decode()
        result = analyze_image(b64, "A test image for verification")
        assert result["passed"] is True
        assert result["confidence"] > 0
        assert result["job_type"] == "image-analysis"

    def test_intent_mismatch_highres(self):
        """Small image with high-res intent should flag mismatch."""
        from agent_market.worker.image_analyzer import analyze_image

        small_png = make_solid_png(20, 20, (100, 150, 200))
        b64 = base64.b64encode(small_png).decode()
        result = analyze_image(b64, "High-resolution print-quality photograph")
        mismatch_issues = [i for i in result["issues"] if i["type"] == "intent_mismatch"]
        assert len(mismatch_issues) > 0


# ─── Image SpotCheck Tests ───────────────────────────────────────────────────

class TestImageSpotCheck:

    def test_generates_valid_output(self):
        """SpotCheck generator should return (image_b64, intent, known_bugs) tuples."""
        from agent_market.manager.image_spot_check import ImageSpotCheckGenerator

        gen = ImageSpotCheckGenerator()
        for _ in range(20):
            image_b64, intent, known_bugs = gen.generate()
            assert isinstance(image_b64, str)
            assert len(image_b64) > 0
            assert isinstance(intent, str)
            assert len(intent) > 0
            assert isinstance(known_bugs, list)

    def test_spot_check_blank_detectable(self):
        """Blank image spot_check should be caught by the analyzer."""
        from agent_market.worker.image_analyzer import analyze_image
        from agent_market.manager.image_spot_check import _make_solid_png

        blank_b64 = _make_solid_png(50, 50, (0, 0, 0))
        result = analyze_image(blank_b64, "Product photograph showing the item")
        # Should detect content issue
        content_issues = [i for i in result["issues"] if i["type"] in ("content", "quality")]
        assert len(content_issues) > 0

    def test_spot_check_clean_no_false_positives(self):
        """Clean spot_check (no bugs) should pass without critical issues."""
        from agent_market.worker.image_analyzer import analyze_image
        from agent_market.manager.image_spot_check import _make_noise_png

        clean_b64 = _make_noise_png(100, 100)
        result = analyze_image(clean_b64, "A simple test image for verification purposes")
        critical_issues = [i for i in result["issues"] if i["severity"] == "critical"]
        assert len(critical_issues) == 0


# ─── Scorer Integration Tests ───────────────────────────────────────────────

class TestScorerImageIntegration:

    def test_scorer_works_with_image_bugs(self):
        """Scorer should evaluate image spot_check bugs correctly."""
        from agent_market.manager.scorer import WorkerScorer

        scorer = WorkerScorer()

        # Simulate: worker found a content issue that matches the known bug
        known_bugs = [
            {"type": "content", "severity": "critical", "line": 0, "description": "Image is blank solid black no product visible"}
        ]
        found_issues = [
            {"type": "content", "severity": "high", "line": 0, "description": "Image appears to be blank or uniform all sampled bytes are identical"}
        ]

        score = scorer.score(
            response_issues=found_issues,
            response_passed=False,
            response_confidence=0.8,
            response_time=0.5,
            is_spot_check=True,
            known_bugs=known_bugs,
        )
        assert score > 0.3  # Should get a decent score for detecting the bug

    def test_scorer_penalizes_missed_image_bugs(self):
        """Missing image bugs should result in low score."""
        from agent_market.manager.scorer import WorkerScorer

        scorer = WorkerScorer()

        known_bugs = [
            {"type": "format", "severity": "critical", "line": 0, "description": "JPEG file is truncated missing end of image marker"}
        ]
        # Worker found nothing
        found_issues = []

        score = scorer.score(
            response_issues=found_issues,
            response_passed=True,
            response_confidence=0.9,
            response_time=0.3,
            is_spot_check=True,
            known_bugs=known_bugs,
        )
        assert score < 0.5  # Should be penalized for missing the bug
