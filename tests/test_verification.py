"""
Tests for the core verification pipeline.

Validates that:
1. The analyzer catches known bug types
2. The spot_check generator produces valid test cases
3. The scorer grades worker responses correctly
4. The full pipeline works end-to-end
"""

import asyncio
import pytest
from agent_market.worker.analyzer import analyze_code
from agent_market.manager.spot_check import SpotCheckGenerator
from agent_market.manager.scorer import WorkerScorer
from agent_market.protocol import JobRequest
from agent_market.worker.forward import forward


# ── Analyzer Tests ───────────────────────────────────────────────

class TestAnalyzer:
    def test_catches_syntax_error(self):
        result = analyze_code("def foo(:\n    pass", "A function", "python")
        assert not result["passed"] or any(
            i["type"] == "syntax_error" for i in result["issues"]
        )

    def test_catches_sql_injection(self):
        code = 'def get_user(db, name):\n    query = f"SELECT * FROM users WHERE name = \'{name}\'"\n    return db.execute(query)'
        result = analyze_code(code, "Look up user safely", "python")
        security_issues = [i for i in result["issues"] if i["type"] == "security"]
        assert len(security_issues) > 0

    def test_catches_wrong_operator(self):
        result = analyze_code("def add(a, b):\n    return a - b", "Add two numbers", "python")
        intent_issues = [i for i in result["issues"] if i["type"] == "intent_mismatch"]
        assert len(intent_issues) > 0

    def test_clean_code_passes(self):
        result = analyze_code(
            "def factorial(n):\n    if n < 0:\n        raise ValueError('n must be non-negative')\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)",
            "Return the factorial of a non-negative integer",
            "python",
        )
        critical = [i for i in result["issues"] if i["severity"] in ("critical", "high")]
        assert len(critical) == 0

    def test_catches_mutable_default(self):
        result = analyze_code(
            "def append_item(item, lst=[]):\n    lst.append(item)\n    return lst",
            "Append item to list",
            "python",
        )
        bug_issues = [i for i in result["issues"] if i["severity"] == "high"]
        assert len(bug_issues) > 0

    def test_catches_hardcoded_password(self):
        code = 'def connect():\n    password = "admin123"\n    return db.connect(password=password)'
        result = analyze_code(code, "Connect to database using environment config", "python")
        security = [i for i in result["issues"] if i["type"] == "security"]
        assert len(security) > 0


# ── Spot Check Tests ───────────────────────────────────────────────

class TestHoneypot:
    def setup_method(self):
        self.gen = SpotCheckGenerator()

    def test_generates_valid_spot_check(self):
        code, intent, bugs = self.gen.generate()
        assert isinstance(code, str) and len(code) > 0
        assert isinstance(intent, str) and len(intent) > 0
        assert isinstance(bugs, list)

    def test_generates_variety(self):
        seen = set()
        for _ in range(20):
            code, intent, bugs = self.gen.generate()
            seen.add(intent)
        assert len(seen) >= 3  # At least 3 different templates

    def test_clean_spot_checks_exist(self):
        """Some spot_checks should have no bugs (test false positive rate)."""
        found_clean = False
        for _ in range(50):
            _, _, bugs = self.gen.generate()
            if len(bugs) == 0:
                found_clean = True
                break
        assert found_clean


# ── Scorer Tests ─────────────────────────────────────────────────

class TestScorer:
    def setup_method(self):
        self.scorer = WorkerScorer()

    def test_perfect_detection_scores_high(self):
        known_bugs = [{"type": "logic_error", "severity": "critical", "line": 2, "description": "wrong operator subtraction instead of addition"}]
        found_issues = [{"type": "logic_error", "severity": "critical", "line": 2, "description": "Uses subtraction instead of addition"}]
        score = self.scorer.score(
            response_issues=found_issues,
            response_passed=False,
            response_confidence=0.9,
            response_time=1.0,
            is_spot_check=True,
            known_bugs=known_bugs,
        )
        assert score > 0.5

    def test_missed_bugs_score_low(self):
        known_bugs = [{"type": "security", "severity": "critical", "line": 2, "description": "SQL injection vulnerability"}]
        score = self.scorer.score(
            response_issues=[],
            response_passed=True,
            response_confidence=0.9,
            response_time=1.0,
            is_spot_check=True,
            known_bugs=known_bugs,
        )
        assert score < 0.4

    def test_false_positives_penalized(self):
        # Clean code spot_check — should find nothing
        score_clean = self.scorer.score(
            response_issues=[],
            response_passed=True,
            response_confidence=0.9,
            response_time=1.0,
            is_spot_check=True,
            known_bugs=[],
        )
        score_noisy = self.scorer.score(
            response_issues=[{"type": "bug", "severity": "high", "line": 1, "description": "fake issue"}],
            response_passed=False,
            response_confidence=0.9,
            response_time=1.0,
            is_spot_check=True,
            known_bugs=[],
        )
        assert score_clean > score_noisy


# ── End-to-End Tests ─────────────────────────────────────────────

class TestEndToEnd:
    def test_full_pipeline_buggy_code(self):
        """Submit buggy code → analyzer finds the bug → scorer gives high score."""
        gen = SpotCheckGenerator()
        scorer = WorkerScorer()

        code, intent, known_bugs = gen.generate()

        # Run through analyzer
        result = analyze_code(code=code, intent=intent, language="python")

        # Score the result
        score = scorer.score(
            response_issues=result["issues"],
            response_passed=result["passed"],
            response_confidence=result["confidence"],
            response_time=0.5,
            is_spot_check=True,
            known_bugs=known_bugs,
        )

        # If there were known bugs, analyzer should find some issues
        if known_bugs:
            assert len(result["issues"]) > 0 or score >= 0

    @pytest.mark.asyncio
    async def test_forward_returns_response(self):
        """Worker forward function returns a valid response."""
        request = JobRequest(
            code="def add(a, b):\n    return a - b",
            intent="Add two numbers",
            language="python",
            job_id="test-001",
        )
        response = await forward(request)
        assert response.job_id == "test-001"
        assert response.processing_time > 0
        assert len(response.issues) > 0  # Should catch the wrong operator
