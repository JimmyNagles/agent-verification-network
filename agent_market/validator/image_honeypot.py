"""
Image Honeypot Generator — Creates synthetic images with known issues for testing miners.

Validators use this to generate images with KNOWN problems, then test whether
miners correctly identify them. This is the ground truth for scoring image analysis.

All images are generated procedurally using only stdlib (struct + zlib).
No Pillow or external image libraries required.
"""

import base64
import random
import struct
import zlib
from typing import Tuple, List, Dict


class ImageHoneypotGenerator:
    """Generate images with known issues for miner testing."""

    def __init__(self):
        self.templates = self._build_templates()

    def generate(self) -> Tuple[str, str, List[Dict]]:
        """
        Generate an image honeypot: base64 image + intent + known bugs.

        Returns:
            (image_b64, intent, known_bugs)
            known_bugs: list of {type, severity, line, description}
        """
        template = random.choice(self.templates)
        variant = random.choice(template["variants"])

        return variant["image_b64"], template["intent"], variant["bugs"]

    def _build_templates(self) -> list:
        """Build the bank of image honeypot templates."""
        return [
            # ── Template 1: Blank/solid-color image ──────────────────
            {
                "intent": "Product photograph showing the item from multiple angles",
                "variants": [
                    {
                        "image_b64": _make_solid_png(50, 50, (0, 0, 0)),
                        "bugs": [
                            {
                                "type": "content",
                                "severity": "critical",
                                "line": 0,
                                "description": "Image is blank (solid black) — no product visible",
                            }
                        ],
                    },
                    {
                        "image_b64": _make_solid_png(50, 50, (255, 255, 255)),
                        "bugs": [
                            {
                                "type": "content",
                                "severity": "critical",
                                "line": 0,
                                "description": "Image is blank (solid white) — no product visible",
                            }
                        ],
                    },
                ],
            },
            # ── Template 2: Truncated JPEG ───────────────────────────
            {
                "intent": "High-resolution company logo for print media",
                "variants": [
                    {
                        "image_b64": _make_truncated_jpeg(),
                        "bugs": [
                            {
                                "type": "format",
                                "severity": "high",
                                "line": 0,
                                "description": "JPEG file is truncated — missing end-of-image marker",
                            }
                        ],
                    },
                ],
            },
            # ── Template 3: Tiny 1x1 image ──────────────────────────
            {
                "intent": "Detailed infographic explaining the product features and specifications",
                "variants": [
                    {
                        "image_b64": _make_solid_png(1, 1, (128, 128, 128)),
                        "bugs": [
                            {
                                "type": "quality",
                                "severity": "high",
                                "line": 0,
                                "description": "Image is 1x1 pixel — too small for an infographic",
                            }
                        ],
                    },
                    {
                        "image_b64": _make_solid_png(5, 5, (200, 100, 50)),
                        "bugs": [
                            {
                                "type": "quality",
                                "severity": "high",
                                "line": 0,
                                "description": "Image is 5x5 pixels — too small for an infographic",
                            }
                        ],
                    },
                ],
            },
            # ── Template 4: Invalid format ───────────────────────────
            {
                "intent": "Professional headshot photograph for corporate website",
                "variants": [
                    {
                        "image_b64": base64.b64encode(b"This is not an image file at all").decode(),
                        "bugs": [
                            {
                                "type": "format",
                                "severity": "critical",
                                "line": 0,
                                "description": "File is not a valid image — unrecognized format",
                            }
                        ],
                    },
                    {
                        "image_b64": base64.b64encode(b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09").decode(),
                        "bugs": [
                            {
                                "type": "format",
                                "severity": "critical",
                                "line": 0,
                                "description": "File is not a valid image — unrecognized binary format",
                            }
                        ],
                    },
                ],
            },
            # ── Template 5: Size mismatch with intent ────────────────
            {
                "intent": "Thumbnail icon for mobile app (32x32 or 64x64)",
                "variants": [
                    {
                        "image_b64": _make_noise_png(500, 500),
                        "bugs": [
                            {
                                "type": "intent_mismatch",
                                "severity": "medium",
                                "line": 0,
                                "description": "Image is 500x500 pixels — too large for a thumbnail icon",
                            }
                        ],
                    },
                ],
            },
            # ── Template 6: Clean image (no bugs) ────────────────────
            # Tests false positive rate — miners should NOT flag these
            {
                "intent": "A simple test image for verification purposes",
                "variants": [
                    {
                        "image_b64": _make_noise_png(100, 100),
                        "bugs": [],
                    },
                ],
            },
            {
                "intent": "Sample photograph for image pipeline testing",
                "variants": [
                    {
                        "image_b64": _make_noise_png(200, 150),
                        "bugs": [],
                    },
                ],
            },
        ]


# ─── Pure-Python Image Construction (stdlib only) ────────────────────────────

def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Create a single PNG chunk: length + type + data + CRC."""
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def _make_png(width: int, height: int, rgb_rows: List[bytes]) -> bytes:
    """
    Construct a valid PNG file from raw RGB row data.
    Each row in rgb_rows should be width*3 bytes (R, G, B per pixel).
    """
    # PNG signature
    signature = b"\x89PNG\r\n\x1a\n"

    # IHDR: width, height, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _make_png_chunk(b"IHDR", ihdr_data)

    # IDAT: filtered scanlines (filter byte 0 = None for each row)
    raw_data = b""
    for row in rgb_rows:
        raw_data += b"\x00" + row  # filter byte + row data

    compressed = zlib.compress(raw_data)
    idat = _make_png_chunk(b"IDAT", compressed)

    # IEND
    iend = _make_png_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def _make_solid_png(width: int, height: int, rgb: tuple) -> str:
    """Create a solid-color PNG and return as base64 string."""
    row = bytes(rgb) * width
    rows = [row] * height
    png_bytes = _make_png(width, height, rows)
    return base64.b64encode(png_bytes).decode()


def _make_noise_png(width: int, height: int) -> str:
    """Create a PNG with random pixel data and return as base64 string."""
    rows = []
    for _ in range(height):
        row = bytes(random.randint(0, 255) for _ in range(width * 3))
        rows.append(row)
    png_bytes = _make_png(width, height, rows)
    return base64.b64encode(png_bytes).decode()


def _make_truncated_jpeg() -> str:
    """Create a truncated JPEG (valid header, missing EOI marker)."""
    # Minimal JPEG: SOI + APP0 (JFIF) + some data, but no EOI
    soi = b"\xff\xd8"
    # APP0 marker
    app0 = b"\xff\xe0"
    app0_length = struct.pack(">H", 16)
    app0_data = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    # Add some fake image data (but no proper SOS/EOI)
    fake_data = bytes(random.randint(0, 255) for _ in range(200))

    jpeg_bytes = soi + app0 + app0_length + app0_data + fake_data
    # Deliberately NOT adding \xff\xd9 (EOI)
    return base64.b64encode(jpeg_bytes).decode()
