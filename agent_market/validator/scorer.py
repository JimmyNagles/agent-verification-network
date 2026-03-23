"""
Miner Scorer — Scores miner responses using multiple signals.

Primary: Honeypot accuracy (did they find known bugs?)
Secondary: Cross-miner consensus (do they agree with others?)
Tertiary: Format compliance (is the response well-structured?)
"""

from typing import List, Dict, Optional
import re


class MinerScorer:
    """Score miner responses objectively."""

    def score(
        self,
        response_issues: List[Dict],
        response_passed: bool,
        response_confidence: float,
        response_time: float,
        is_honeypot: bool = False,
        known_bugs: Optional[List[Dict]] = None,
        all_responses: Optional[List] = None,
    ) -> float:
        """
        Score a miner's response from 0.0 to 1.0.

        Args:
            response_issues: Issues the miner found
            response_passed: Miner's pass/fail verdict
            response_confidence: Miner's confidence score
            response_time: Processing time in seconds
            is_honeypot: Whether this was a synthetic test
            known_bugs: Ground truth bugs (for honeypots)
            all_responses: All miner responses (for consensus)
        """
        score = 0.0

        # ── PRIMARY: Honeypot accuracy (60% weight) ──────────────
        if is_honeypot and known_bugs is not None:
            honeypot_score = self._score_honeypot(
                response_issues, response_passed, known_bugs
            )
            score += 0.6 * honeypot_score

        # ── SECONDARY: Consensus alignment (20% weight) ──────────
        if all_responses and len(all_responses) > 1:
            consensus_score = self._score_consensus(
                response_issues, all_responses
            )
            score += 0.2 * consensus_score
        elif not is_honeypot:
            # No consensus possible — give partial credit for format
            score += 0.1

        # ── TERTIARY: Format compliance (10% weight) ──────────────
        format_score = self._score_format(response_issues)
        score += 0.1 * format_score

        # ── QUATERNARY: Speed bonus (10% weight) ──────────────────
        speed_score = self._score_speed(response_time)
        score += 0.1 * speed_score

        return max(0.0, min(1.0, score))

    def _score_honeypot(
        self,
        found_issues: List[Dict],
        miner_passed: bool,
        known_bugs: List[Dict],
    ) -> float:
        """Score based on honeypot ground truth."""

        if not known_bugs:
            # Clean code honeypot — test false positive rate
            if len(found_issues) == 0 and miner_passed:
                return 1.0  # Correctly identified clean code
            else:
                # Penalize false positives
                false_positive_penalty = min(1.0, len(found_issues) * 0.3)
                return max(0.0, 1.0 - false_positive_penalty)

        # Buggy code honeypot — test detection rate
        total_bugs = len(known_bugs)
        detected = 0

        for known_bug in known_bugs:
            bug_type = known_bug.get("type", "").lower()
            bug_desc = known_bug.get("description", "").lower()
            bug_line = known_bug.get("line", 0)

            for found in found_issues:
                found_type = found.get("type", "").lower()
                found_desc = found.get("description", "").lower()
                found_line = found.get("line", 0)

                # Match by type similarity
                type_match = (
                    bug_type in found_type
                    or found_type in bug_type
                    or self._types_related(bug_type, found_type)
                )

                # Match by description overlap
                desc_keywords = set(bug_desc.split()) - {"the", "a", "is", "in", "of", "to"}
                found_keywords = set(found_desc.split()) - {"the", "a", "is", "in", "of", "to"}
                keyword_overlap = len(desc_keywords & found_keywords)
                desc_match = keyword_overlap >= 2

                # Match by line proximity
                line_match = (
                    bug_line == 0
                    or found_line == 0
                    or abs(bug_line - found_line) <= 2
                )

                if (type_match or desc_match) and line_match:
                    detected += 1
                    break

        detection_rate = detected / total_bugs if total_bugs > 0 else 0

        # Penalize false positives (issues that don't match any known bug)
        unmatched = max(0, len(found_issues) - detected)
        false_positive_rate = unmatched / max(1, len(found_issues))
        false_positive_penalty = false_positive_rate * 0.3

        # Penalize if miner said "passed" when there are known bugs
        pass_penalty = 0.2 if miner_passed and total_bugs > 0 else 0.0

        return max(0.0, detection_rate - false_positive_penalty - pass_penalty)

    def _score_consensus(
        self,
        response_issues: List[Dict],
        all_responses: List,
    ) -> float:
        """Score based on agreement with other miners."""
        if not all_responses or len(all_responses) < 2:
            return 0.5  # Neutral if no comparison possible

        # Count how many miners agree on pass/fail
        our_count = len(response_issues)
        has_issues = our_count > 0

        other_counts = []
        for resp in all_responses:
            if resp is not None and hasattr(resp, "issues"):
                other_counts.append(len(resp.issues) > 0)

        if not other_counts:
            return 0.5

        # What's the consensus?
        majority_has_issues = sum(other_counts) > len(other_counts) / 2

        if has_issues == majority_has_issues:
            return 1.0  # Agrees with majority
        else:
            return 0.2  # Disagrees with majority

    def _score_format(self, issues: List[Dict]) -> float:
        """Score based on response format quality."""
        if not issues:
            return 0.8  # No issues is fine (might be clean code)

        score = 0.0
        for issue in issues:
            has_type = bool(issue.get("type"))
            has_severity = bool(issue.get("severity"))
            has_description = bool(issue.get("description"))
            has_line = issue.get("line", 0) > 0

            completeness = sum([has_type, has_severity, has_description, has_line]) / 4
            score += completeness

        return score / len(issues) if issues else 0.0

    def _score_speed(self, processing_time: float) -> float:
        """Bonus for faster responses (quality threshold already met)."""
        if processing_time <= 0:
            return 0.5
        if processing_time < 2:
            return 1.0
        if processing_time < 5:
            return 0.8
        if processing_time < 10:
            return 0.5
        return 0.2

    def _types_related(self, type_a: str, type_b: str) -> bool:
        """Check if two issue types are semantically related."""
        related_groups = [
            {"bug", "logic_error", "off_by_one", "wrong_return", "intent_mismatch", "incomplete"},
            {"security", "sql_injection", "hardcoded", "injection"},
            {"missing_edge_case", "null_check", "type_error", "edge_case", "intent_mismatch"},
            {"code_quality", "bad_practice", "reliability"},
            {"content", "quality", "format", "blank", "truncated", "intent_mismatch", "content_mismatch", "missing_element"},
        ]
        for group in related_groups:
            a_match = any(t in type_a for t in group)
            b_match = any(t in type_b for t in group)
            if a_match and b_match:
                return True
        return False
