"""
tests/test_onboarding_agent.py

Tests for OnboardingAgent — question definitions, chip cleaning,
profile mapping. NIM calls are mocked.
Run with: pytest tests/test_onboarding_agent.py
"""

import pytest
from unittest.mock import MagicMock, patch
from agents.onboarding_agent import OnboardingAgent, ONBOARDING_QUESTIONS


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def agent():
    mock_nim = MagicMock()
    mock_nim.complete_fast.return_value = "HIPAA-compliant deployment inside hospital perimeter."
    mock_nim.complete_json.return_value = [
        "Medical imaging AI platform",
        "Radiology anomaly detection",
        "Clinical AI for hospitals",
    ]
    return OnboardingAgent(nim_client=mock_nim)


@pytest.fixture
def partial_profile():
    return {
        "vision": "AI anomaly detection for radiology",
        "target_user": "Radiologists in mid-size hospitals",
        "product_stage": "Working prototype on local machine",
    }


# ── Question definitions ──────────────────────────────────────────────────────

class TestQuestionDefinitions:

    def test_13_questions_defined(self):
        assert len(ONBOARDING_QUESTIONS) == 13

    def test_all_questions_have_required_fields(self):
        for q in ONBOARDING_QUESTIONS:
            assert "id" in q
            assert "chapter" in q
            assert "question" in q
            assert "field" in q
            assert "multi" in q

    def test_chapters_are_valid(self):
        valid_chapters = {"vision", "technical", "team", "market", "ask"}
        for q in ONBOARDING_QUESTIONS:
            assert q["chapter"] in valid_chapters

    def test_question_ids_unique(self):
        ids = [q["id"] for q in ONBOARDING_QUESTIONS]
        assert len(ids) == len(set(ids))

    def test_vision_chapter_has_3_questions(self):
        vision = [q for q in ONBOARDING_QUESTIONS if q["chapter"] == "vision"]
        assert len(vision) == 3

    def test_technical_chapter_has_4_questions(self):
        technical = [q for q in ONBOARDING_QUESTIONS if q["chapter"] == "technical"]
        assert len(technical) == 4

    def test_multi_select_questions_exist(self):
        multi = [q for q in ONBOARDING_QUESTIONS if q["multi"]]
        assert len(multi) >= 2

    def test_get_question_by_id(self, agent):
        q = agent.get_question("q1")
        assert q is not None
        assert q["chapter"] == "vision"

    def test_get_question_invalid_id(self, agent):
        q = agent.get_question("q99")
        assert q is None

    def test_get_chapter_questions(self, agent):
        vision_qs = agent.get_chapter_questions("vision")
        assert len(vision_qs) == 3
        assert all(q["chapter"] == "vision" for q in vision_qs)


# ── Chip prediction ───────────────────────────────────────────────────────────

class TestChipPrediction:

    def test_returns_list(self, agent, partial_profile):
        chips = agent.predict_chips(partial_profile, "What is your deployment target?")
        assert isinstance(chips, list)

    def test_chips_are_strings(self, agent, partial_profile):
        chips = agent.predict_chips(partial_profile, "What is your deployment target?")
        assert all(isinstance(c, str) for c in chips)

    def test_max_4_chips(self, agent, partial_profile):
        chips = agent.predict_chips(partial_profile, "What is your deployment target?", n=4)
        assert len(chips) <= 4

    def test_empty_profile_returns_empty(self, agent):
        chips = agent.predict_chips({}, "What are you building?")
        assert chips == []

    def test_nim_failure_returns_empty(self, partial_profile):
        mock_nim = MagicMock()
        mock_nim.complete_json.side_effect = Exception("NIM timeout")
        agent = OnboardingAgent(nim_client=mock_nim)
        chips = agent.predict_chips(partial_profile, "next question")
        assert chips == []


# ── Chip cleaning ─────────────────────────────────────────────────────────────

class TestChipCleaning:

    def test_strips_whitespace(self):
        cleaned = OnboardingAgent._clean_chip("  Medical imaging AI  ")
        assert cleaned == "Medical imaging AI"

    def test_removes_leading_bullet(self):
        cleaned = OnboardingAgent._clean_chip("• Something important")
        assert cleaned == "Something important"

    def test_removes_leading_number(self):
        cleaned = OnboardingAgent._clean_chip("1 First option")
        assert cleaned == "First option"

    def test_truncates_long_chips(self):
        long = "This is a very long answer that goes way beyond twelve words and should be truncated"
        cleaned = OnboardingAgent._clean_chip(long)
        assert len(cleaned.split()) <= 14  # 12 + ellipsis word


# ── Profile context ───────────────────────────────────────────────────────────

class TestProfileContext:

    def test_to_context_includes_known_fields(self, partial_profile):
        ctx = OnboardingAgent._profile_to_context(partial_profile)
        assert "Building" in ctx
        assert "radiology" in ctx.lower()

    def test_empty_profile_returns_placeholder(self):
        ctx = OnboardingAgent._profile_to_context({})
        assert "No context yet" in ctx

    def test_list_values_joined(self):
        profile = {"current_stack": ["PyTorch", "MONAI"]}
        ctx = OnboardingAgent._profile_to_context(profile)
        assert "PyTorch" in ctx
        assert "MONAI" in ctx


# ── Field mapping ─────────────────────────────────────────────────────────────

class TestFieldMapping:

    def test_vision_maps_to_product(self, agent):
        answers = {"vision": "AI for radiology"}
        mapped = agent._map_answers_to_profile(answers)
        assert mapped.get("product") == "AI for radiology"

    def test_compliance_maps_correctly(self, agent):
        answers = {"compliance": "HIPAA"}
        mapped = agent._map_answers_to_profile(answers)
        assert mapped.get("compliance_requirements") == "HIPAA"

    def test_defaults_populated(self, agent):
        answers = {}
        mapped = agent._map_answers_to_profile(answers)
        assert "domain" in mapped
        assert "deployment_target" in mapped
        assert "twelve_month_goal" in mapped