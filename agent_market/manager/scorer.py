"""
Worker Scorer — Rates worker responses using multiple signals.

Primary: Spot check accuracy (did they find known bugs?) — 60%
Secondary: Cross-worker consensus via issue-level F1 — 25%
Tertiary: Format compliance (is the response well-structured?) — 10%
Quaternary: Speed bonus (faster = slight edge) — 5%

Quality gate: rating >= 0.70 to pass and receive payment.
"""

from typing import List, Dict, Optional
import re

# Quality gate threshold — workers below this fail and get no payment
QUALITY_GATE = 0.70


class WorkerScorer:
    """Rate worker responses objectively."""

    def score(
        self,
        response_issues: List[Dict],
        response_passed: bool,
        response_confidence: float,
        response_time: float,
        is_spot_check: bool = False,
        known_bugs: Optional[List[Dict]] = None,
        all_responses: Optional[List] = None,
    ) -> float:
        """
        Rate a worker's response from 0.0 to 1.0.

        Args:
            response_issues: Issues the worker found
            response_passed: Worker's pass/fail verdict
            response_confidence: Worker's confidence score
            response_time: Processing time in seconds
            is_spot_check: Whether this was a spot check
            known_bugs: Ground truth bugs (for spot checks)
            all_responses: All worker responses (for consensus F1)
        """
        score = 0.0

        # ── PRIMARY: Spot check accuracy (60% weight) ─────────────
        if is_spot_check and known_bugs is not None:
            spot_check_score = self._score_spot_check(
                response_issues, response_passed, known_bugs
            )
            score += 0.60 * spot_check_score

        # ── SECONDARY: Consensus alignment (25% weight) ──────────
        if all_responses and len(all_responses) > 1:
            consensus_score = self._score_consensus_f1(
                response_issues, all_responses
            )
            score += 0.25 * consensus_score
        elif not is_spot_check:
            # No consensus possible (solo worker) — give partial credit
            score += 0.10

        # ── TERTIARY: Format compliance (10% weight) ──────────────
        format_score = self._score_format(response_issues)
        score += 0.10 * format_score

        # ── QUATERNARY: Speed bonus (5% weight) ──────────────────
        speed_score = self._score_speed(response_time)
        score += 0.05 * speed_score

        return max(0.0, min(1.0, score))

    def passes_gate(self, score: float) -> bool:
        """Check if a worker's score passes the quality gate."""
        return score >= QUALITY_GATE

    def _score_spot_check(
        self,
        found_issues: List[Dict],
        worker_passed: bool,
        known_bugs: List[Dict],
    ) -> float:
        """Score based on spot check ground truth."""

        if not known_bugs:
            # Clean code spot check — test false positive rate
            if len(found_issues) == 0 and worker_passed:
                return 1.0  # Correctly identified clean code
            else:
                # Penalize false positives
                false_positive_penalty = min(1.0, len(found_issues) * 0.3)
                return max(0.0, 1.0 - false_positive_penalty)

        # Buggy code spot check — test detection rate
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

                type_match = (
                    bug_type in found_type
                    or found_type in bug_type
                    or self._types_related(bug_type, found_type)
                )

                desc_keywords = set(bug_desc.split()) - {"the", "a", "is", "in", "of", "to"}
                found_keywords = set(found_desc.split()) - {"the", "a", "is", "in", "of", "to"}
                keyword_overlap = len(desc_keywords & found_keywords)
                desc_match = keyword_overlap >= 2

                line_match = (
                    bug_line == 0
                    or found_line == 0
                    or abs(bug_line - found_line) <= 2
                )

                if (type_match or desc_match) and line_match:
                    detected += 1
                    break

        detection_rate = detected / total_bugs if total_bugs > 0 else 0

        unmatched = max(0, len(found_issues) - detected)
        false_positive_rate = unmatched / max(1, len(found_issues))
        false_positive_penalty = false_positive_rate * 0.3

        pass_penalty = 0.2 if worker_passed and total_bugs > 0 else 0.0

        return max(0.0, detection_rate - false_positive_penalty - pass_penalty)

    def _score_consensus_f1(
        self,
        response_issues: List[Dict],
        all_responses: List,
    ) -> float:
        """
        Score based on issue-level F1 against peer consensus.

        Instead of just pass/fail majority, we:
        1. Normalize each issue into a canonical key (type + line bucket)
        2. Build a consensus set from issues reported by >= 50% of workers
        3. Score this worker's F1 against the consensus set
        """
        if not all_responses or len(all_responses) < 2:
            return 0.5  # Neutral if no comparison possible

        # Collect all issues from all workers into canonical keys
        all_issue_keys: List[List[str]] = []
        for resp in all_responses:
            if resp is None:
                continue
            issues = resp.issues if hasattr(resp, "issues") else resp.get("issues", [])
            keys = []
            for issue in issues:
                key = self._canonicalize_issue(issue)
                if key:
                    keys.append(key)
            all_issue_keys.append(keys)

        if len(all_issue_keys) < 2:
            return 0.5

        # Build consensus set: issues found by >= 50% of workers
        from collections import Counter
        all_keys_flat = [k for keys in all_issue_keys for k in keys]
        key_counts = Counter(all_keys_flat)
        threshold = len(all_issue_keys) / 2
        consensus_set = {k for k, count in key_counts.items() if count >= threshold}

        if not consensus_set:
            # No consensus emerged — everyone found different things
            return 0.5

        # Score this worker's F1 against consensus
        worker_keys = set()
        for issue in response_issues:
            key = self._canonicalize_issue(issue)
            if key:
                worker_keys.add(key)

        if not worker_keys and not consensus_set:
            return 1.0  # Both empty — agreement on clean code

        true_positives = len(worker_keys & consensus_set)
        precision = true_positives / len(worker_keys) if worker_keys else 0.0
        recall = true_positives / len(consensus_set) if consensus_set else 0.0

        if precision + recall == 0:
            return 0.0

        f1 = 2 * (precision * recall) / (precision + recall)
        return f1

    def _canonicalize_issue(self, issue: Dict) -> Optional[str]:
        """
        Normalize an issue into a canonical key for comparison.

        Format: type_bucket:line_bucket:keyword_hash
        Line bucket groups lines within +/-2 of each other.
        """
        issue_type = issue.get("type", "").lower().strip()
        line = issue.get("line", 0)
        desc = issue.get("description", "").lower()

        if not issue_type and not desc:
            return None

        # Type bucket — normalize related types
        type_bucket = issue_type
        for group_name, group_types in [
            ("logic", {"bug", "logic_error", "off_by_one", "wrong_return", "intent_mismatch", "incomplete"}),
            ("security", {"security", "sql_injection", "hardcoded", "injection"}),
            ("edge_case", {"missing_edge_case", "null_check", "type_error", "edge_case"}),
            ("quality", {"code_quality", "bad_practice", "reliability"}),
            ("content", {"content", "quality", "format", "blank", "truncated", "content_mismatch", "missing_element"}),
        ]:
            if any(t in issue_type for t in group_types):
                type_bucket = group_name
                break

        # Line bucket — group nearby lines
        line_bucket = (line // 3) * 3 if line > 0 else 0

        # Keyword extraction — top 3 meaningful words from description
        stop_words = {"the", "a", "is", "in", "of", "to", "and", "or", "but", "not", "for", "with", "this", "that", "are", "was", "be", "has", "have", "does", "code"}
        keywords = sorted(
            [w for w in desc.split() if w not in stop_words and len(w) > 2],
            key=len, reverse=True
        )[:3]
        keyword_hash = "_".join(keywords) if keywords else "none"

        return f"{type_bucket}:{line_bucket}:{keyword_hash}"

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
        """Bonus for faster responses."""
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


# Backward-compatible alias
MinerScorer = WorkerScorer
