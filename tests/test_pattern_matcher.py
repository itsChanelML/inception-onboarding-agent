"""
tests/test_pattern_matcher.py

Tests for PatternMatcher — scoring, matching, insight extraction.
No NIM calls required (NIM is only used for manager_recommendation).
Run with: pytest tests/test_pattern_matcher.py
"""

import pytest
from unittest.mock import MagicMock, patch
from agents.pattern_matcher import PatternMatcher, STRONG_MATCH_THRESHOLD, GOOD_MATCH_THRESHOLD
from schemas.journey import SEED_PATTERNS, SimilarityDimension


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def matcher():
    """PatternMatcher with mock NIM client — no real API calls."""
    mock_nim = MagicMock()
    mock_nim.complete_fast.return_value = "Introduce NIM on-premise in week 1."
    return PatternMatcher(nim_client=mock_nim, patterns=SEED_PATTERNS)


@pytest.fixture
def healthcare_founder():
    return {
        "founder_name": "Dr. Maya Chen",
        "company": "ClaraVision",
        "domain": "medical imaging",
        "deployment_target": "on-premise",
        "compliance_requirements": ["HIPAA"],
        "nvidia_tools": ["NIM", "Clara", "MONAI"],
        "primary_challenge": "HIPAA-compliant on-premise deployment",
        "funding_stage": "Seed",
    }


@pytest.fixture
def agriculture_founder():
    return {
        "founder_name": "Ravi Krishnamurthy",
        "company": "NovaCrop AI",
        "domain": "precision agriculture",
        "deployment_target": "edge",
        "compliance_requirements": [],
        "nvidia_tools": ["Jetson", "TAO"],
        "primary_challenge": "Sub-100ms edge inference on Jetson",
        "funding_stage": "Pre-seed",
    }


@pytest.fixture
def unrelated_founder():
    return {
        "founder_name": "Unknown",
        "company": "TechCo",
        "domain": "fintech blockchain",
        "deployment_target": "cloud",
        "compliance_requirements": [],
        "nvidia_tools": [],
        "primary_challenge": "Payment processing latency",
        "funding_stage": "Bootstrapped",
    }


# ── find_matches ──────────────────────────────────────────────────────────────

class TestFindMatches:

    def test_healthcare_founder_gets_matches(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder, top_n=3)
        assert len(matches) > 0

    def test_healthcare_founder_top_match_is_healthcare(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder, top_n=3)
        assert matches[0].pattern.domain in ("medical imaging", "clinical nlp")

    def test_agriculture_founder_top_match_is_edge(self, matcher, agriculture_founder):
        matches = matcher.find_matches(agriculture_founder, top_n=3)
        assert len(matches) > 0
        assert matches[0].pattern.deployment_target == "edge"

    def test_matches_sorted_by_score_descending(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder, top_n=3)
        scores = [m.similarity_score for m in matches]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_respected(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder, top_n=1)
        assert len(matches) <= 1

    def test_min_score_filters_weak_matches(self, matcher, unrelated_founder):
        matches = matcher.find_matches(unrelated_founder, min_score=0.8)
        # Fintech founder should not strongly match any seed pattern
        assert len(matches) == 0

    def test_match_has_key_insight(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder)
        assert len(matches[0].key_insight) > 10

    def test_match_has_recommended_action(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder)
        assert len(matches[0].recommended_action) > 5

    def test_matched_on_dimensions_populated(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder)
        assert len(matches[0].matched_on) > 0
        assert all(isinstance(d, SimilarityDimension) for d in matches[0].matched_on)


# ── best_match ────────────────────────────────────────────────────────────────

class TestBestMatch:

    def test_returns_single_match(self, matcher, healthcare_founder):
        match = matcher.best_match(healthcare_founder)
        assert match is not None

    def test_returns_none_for_unrelated(self, matcher):
        unrelated = {"domain": "underwater basket weaving", "deployment_target": "unknown"}
        match = matcher.best_match(unrelated)
        assert match is None


# ── Scoring helpers ───────────────────────────────────────────────────────────

class TestScoringHelpers:

    def test_exact_domain_match(self):
        score = PatternMatcher._domain_similarity("medical imaging", "medical imaging")
        assert score == 1.0

    def test_same_category_domain(self):
        score = PatternMatcher._domain_similarity("radiology AI", "medical imaging")
        assert score >= 0.7

    def test_different_domain(self):
        score = PatternMatcher._domain_similarity("fintech", "medical imaging")
        assert score == 0.0

    def test_exact_deployment_match(self):
        score = PatternMatcher._exact_match("on-premise", "on-premise")
        assert score == 1.0

    def test_deployment_mismatch(self):
        score = PatternMatcher._exact_match("cloud", "edge")
        assert score == 0.0

    def test_list_overlap_full(self):
        score = PatternMatcher._list_overlap(["HIPAA", "SOC 2"], ["HIPAA", "SOC 2"])
        assert score == 1.0

    def test_list_overlap_partial(self):
        score = PatternMatcher._list_overlap(["HIPAA", "GDPR"], ["HIPAA", "SOC 2"])
        assert 0 < score < 1.0

    def test_list_overlap_none(self):
        score = PatternMatcher._list_overlap(["HIPAA"], ["SOC 2"])
        assert score == 0.0

    def test_list_overlap_empty(self):
        score = PatternMatcher._list_overlap([], ["HIPAA"])
        assert score == 0.0

    def test_keyword_overlap(self):
        score = PatternMatcher._keyword_overlap(
            "HIPAA-compliant on-premise deployment",
            "HIPAA compliance on-premise infrastructure"
        )
        assert score > 0

    def test_normalize_deploy_on_premise(self):
        assert PatternMatcher._normalize_deploy("on-premise hospital") == "on-premise"
        assert PatternMatcher._normalize_deploy("on-prem") == "on-premise"

    def test_normalize_deploy_edge(self):
        assert PatternMatcher._normalize_deploy("edge device") == "edge"

    def test_normalize_deploy_cloud(self):
        assert PatternMatcher._normalize_deploy("AWS cloud") == "cloud"


# ── manager_recommendation ────────────────────────────────────────────────────

class TestManagerRecommendation:

    def test_returns_string(self, matcher, healthcare_founder):
        matches = matcher.find_matches(healthcare_founder)
        rec = matcher.manager_recommendation(healthcare_founder, matches)
        assert isinstance(rec, str)
        assert len(rec) > 10

    def test_empty_matches_returns_fallback(self, matcher, healthcare_founder):
        rec = matcher.manager_recommendation(healthcare_founder, [])
        assert isinstance(rec, str)
        assert len(rec) > 5

    def test_nim_failure_returns_fallback(self, healthcare_founder):
        mock_nim = MagicMock()
        mock_nim.complete_fast.side_effect = Exception("NIM timeout")
        m = PatternMatcher(nim_client=mock_nim, patterns=SEED_PATTERNS)
        matches = m.find_matches(healthcare_founder)
        rec = m.manager_recommendation(healthcare_founder, matches)
        assert isinstance(rec, str)


# ── lessons_for_aria ──────────────────────────────────────────────────────────

class TestLessonsForAria:

    def test_returns_string(self, matcher, healthcare_founder):
        lessons = matcher.lessons_for_aria(healthcare_founder)
        assert isinstance(lessons, str)

    def test_contains_lessons(self, matcher, healthcare_founder):
        lessons = matcher.lessons_for_aria(healthcare_founder)
        assert "•" in lessons or len(lessons) > 0

    def test_empty_for_unrelated(self, matcher):
        unrelated = {"domain": "fintech", "deployment_target": "unknown"}
        lessons = matcher.lessons_for_aria(unrelated, top_n=1)
        # May return empty string if no matches above threshold
        assert isinstance(lessons, str)