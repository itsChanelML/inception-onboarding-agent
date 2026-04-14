"""
tests/test_schemas.py

Tests for Pydantic schemas — founder profile, milestone, ticket, journey.
No external dependencies required. Run with: pytest tests/test_schemas.py
"""

import pytest
from schemas.founder_profile import FounderProfile
from schemas.milestone import Milestone, MilestoneStatus, SubTask, default_milestones
from schemas.ticket import Ticket, TicketCategory, TicketUrgency, TicketStatus
from schemas.journey import JourneyPattern, PatternMatch, SimilarityDimension, JourneyOutcome, SEED_PATTERNS


# ── FounderProfile ────────────────────────────────────────────────────────────

class TestFounderProfile:

    def _base(self, **kwargs):
        defaults = dict(
            founder_name="Dr. Maya Chen",
            company="ClaraVision",
            domain="Medical Imaging AI",
            primary_challenge="HIPAA-compliant on-premise deployment",
            deployment_target="on-premise",
            twelve_month_goal="First signed hospital partnership",
        )
        defaults.update(kwargs)
        return FounderProfile(**defaults)

    def test_basic_creation(self):
        p = self._base()
        assert p.founder_name == "Dr. Maya Chen"
        assert p.company == "ClaraVision"

    def test_domain_normalized_to_lowercase(self):
        p = self._base(domain="Medical Imaging AI")
        assert p.domain == "medical imaging ai"

    def test_deployment_target_normalization(self):
        p = self._base(deployment_target="on-premise hospital deployment")
        assert p.deployment_target == "on-premise"

        p2 = self._base(deployment_target="cloud (AWS)")
        assert p2.deployment_target == "cloud"

        p3 = self._base(deployment_target="edge device")
        assert p3.deployment_target == "edge"

    def test_compliance_from_string(self):
        p = self._base(compliance_requirements="HIPAA, SOC 2")
        assert "HIPAA" in p.compliance_requirements
        assert "SOC 2" in p.compliance_requirements

    def test_compliance_from_list(self):
        p = self._base(compliance_requirements=["HIPAA", "GDPR"])
        assert len(p.compliance_requirements) == 2

    def test_is_healthcare_true(self):
        p = self._base(domain="medical imaging")
        assert p.is_healthcare is True

    def test_is_healthcare_false(self):
        p = self._base(domain="precision agriculture")
        assert p.is_healthcare is False

    def test_needs_hipaa(self):
        p = self._base(compliance_requirements=["HIPAA"])
        assert p.needs_hipaa is True

    def test_needs_hipaa_false(self):
        p = self._base(compliance_requirements=["SOC 2"])
        assert p.needs_hipaa is False

    def test_first_name(self):
        p = self._base(founder_name="Dr. Maya Chen")
        assert p.first_name == "Dr."

    def test_version_default(self):
        p = self._base()
        assert p.version == 1

    def test_bumped_version(self):
        p = self._base()
        p2 = p.bumped_version()
        assert p2.version == 2
        assert p.version == 1  # original unchanged

    def test_to_prompt_context(self):
        p = self._base(nvidia_tools=["NIM", "Clara"])
        ctx = p.to_prompt_context()
        assert "Dr. Maya Chen" in ctx
        assert "ClaraVision" in ctx
        assert "NIM" in ctx

    def test_extra_fields_allowed(self):
        # Legacy JSON files may have extra fields
        p = self._base(_slug="claravision", join_date="2026-01-01")
        assert p.join_date == "2026-01-01"

    def test_empty_nvidia_tools_default(self):
        p = self._base()
        assert p.nvidia_tools == []
        assert p.has_nvidia_stack is False

    def test_stack_summary(self):
        p = self._base(nvidia_tools=["NIM", "Clara", "MONAI"])
        assert p.stack_summary == "NIM · Clara · MONAI"


# ── Milestone ─────────────────────────────────────────────────────────────────

class TestMilestone:

    def _base(self, **kwargs):
        defaults = dict(
            id=1,
            title="Infrastructure Foundation",
            description="Core infrastructure running",
            month_range="Month 1",
        )
        defaults.update(kwargs)
        return Milestone(**defaults)

    def test_basic_creation(self):
        m = self._base()
        assert m.title == "Infrastructure Foundation"
        assert m.status == MilestoneStatus.LOCKED

    def test_is_complete_false_by_default(self):
        m = self._base()
        assert m.is_complete is False

    def test_is_complete_at_100_pct(self):
        m = self._base(pct=100, status=MilestoneStatus.COMPLETE)
        assert m.is_complete is True

    def test_unlock(self):
        m = self._base()
        unlocked = m.unlock()
        assert unlocked.status == MilestoneStatus.ACTIVE
        assert unlocked.started_at is not None

    def test_complete(self):
        m = self._base(status=MilestoneStatus.ACTIVE, pct=80)
        completed = m.complete()
        assert completed.status == MilestoneStatus.COMPLETE
        assert completed.pct == 100
        assert completed.completed_at is not None

    def test_sub_tasks_pct(self):
        tasks = [
            SubTask(id="t1", title="Task 1", complete=True),
            SubTask(id="t2", title="Task 2", complete=True),
            SubTask(id="t3", title="Task 3", complete=False),
            SubTask(id="t4", title="Task 4", complete=False),
        ]
        m = self._base(sub_tasks=tasks)
        assert m.sub_tasks_complete == 2
        assert m.sub_tasks_total == 4
        assert m.sub_task_pct == 50

    def test_default_milestones_count(self):
        milestones = default_milestones()
        assert len(milestones) == 7

    def test_default_milestones_first_two_active(self):
        milestones = default_milestones()
        assert milestones[0].status == MilestoneStatus.ACTIVE
        assert milestones[1].status == MilestoneStatus.ACTIVE
        assert milestones[2].status == MilestoneStatus.LOCKED

    def test_pct_bounds(self):
        with pytest.raises(Exception):
            self._base(pct=101)
        with pytest.raises(Exception):
            self._base(pct=-1)


# ── Ticket ────────────────────────────────────────────────────────────────────

class TestTicket:

    def _base(self, **kwargs):
        defaults = dict(
            founder_slug="claravision",
            question="How do I configure NIM egress policy on GKE?",
        )
        defaults.update(kwargs)
        return Ticket(**defaults)

    def test_basic_creation(self):
        t = self._base()
        assert t.founder_slug == "claravision"
        assert t.status == TicketStatus.OPEN

    def test_ticket_id_generated(self):
        t = self._base()
        assert len(t.ticket_id) == 8

    def test_urgent_technical_routes_to_manager(self):
        t = self._base(
            category=TicketCategory.TECHNICAL,
            urgency=TicketUrgency.URGENT
        )
        assert t.routing == "manager"
        assert t.needs_human is True

    def test_general_technical_routes_to_aria(self):
        t = self._base(
            category=TicketCategory.TECHNICAL,
            urgency=TicketUrgency.GENERAL
        )
        assert t.routing == "aria"
        assert t.aria_can_handle is True

    def test_moderate_technical_routes_to_aria_then_manager(self):
        t = self._base(
            category=TicketCategory.TECHNICAL,
            urgency=TicketUrgency.MODERATE
        )
        assert t.routing == "aria_then_manager"

    def test_with_aria_draft(self):
        t = self._base()
        t2 = t.with_aria_draft("Here's the answer...", confidence=0.9)
        assert t2.aria_draft == "Here's the answer..."
        assert t2.aria_confidence == 0.9
        assert t2.status == TicketStatus.ARIA_DRAFT

    def test_with_resolution(self):
        t = self._base()
        t2 = t.with_resolution("Set NetworkPolicy before NIM pod deploys.", manager="Chanel")
        assert t2.status == TicketStatus.RESOLVED
        assert t2.manager_name == "Chanel"
        assert t2.resolved_at is not None

    def test_is_open(self):
        t = self._base()
        assert t.is_open is True

    def test_is_resolved(self):
        t = self._base()
        t2 = t.with_resolution("Fixed.")
        assert t2.is_resolved is True

    def test_routing_label(self):
        t = self._base(
            category=TicketCategory.TECHNICAL,
            urgency=TicketUrgency.URGENT
        )
        assert "Manager" in t.routing_label

    def test_question_stripped(self):
        t = self._base(question="   How do I configure NIM?   ")
        assert t.question == "How do I configure NIM?"


# ── JourneyPattern & PatternMatch ─────────────────────────────────────────────

class TestJourneyPattern:

    def test_seed_patterns_load(self):
        assert len(SEED_PATTERNS) >= 3

    def test_seed_pattern_healthcare(self):
        healthcare = next(p for p in SEED_PATTERNS if "medical imaging" in p.domain)
        assert healthcare.outcome == JourneyOutcome.PARTNERSHIP_SIGNED
        assert len(healthcare.lessons) > 0
        assert healthcare.milestone_velocity > 0

    def test_seed_pattern_edge_ai(self):
        edge = next(p for p in SEED_PATTERNS if "agriculture" in p.domain)
        assert edge.deployment_target == "edge"
        assert "Jetson" in " ".join(edge.nvidia_tools)

    def test_was_successful(self):
        p = SEED_PATTERNS[0]
        assert p.was_successful is True

    def test_lessons_formatted(self):
        p = SEED_PATTERNS[0]
        formatted = p.lessons_formatted
        assert "•" in formatted
        assert len(formatted) > 10

    def test_pattern_match_similarity_pct(self):
        match = PatternMatch(
            pattern=SEED_PATTERNS[0],
            similarity_score=0.86,
            matched_on=[SimilarityDimension.DOMAIN, SimilarityDimension.COMPLIANCE],
            key_insight="86% match with healthcare founder",
            recommended_action="Introduce NIM on-premise in first meeting",
        )
        assert match.similarity_pct == 86
        assert match.match_label == "Strong match"

    def test_pattern_match_good(self):
        match = PatternMatch(
            pattern=SEED_PATTERNS[0],
            similarity_score=0.65,
            matched_on=[SimilarityDimension.DOMAIN],
            key_insight="Good match",
            recommended_action="Action",
        )
        assert match.match_label == "Good match"

    def test_pattern_match_partial(self):
        match = PatternMatch(
            pattern=SEED_PATTERNS[0],
            similarity_score=0.40,
            matched_on=[SimilarityDimension.FUNDING_STAGE],
            key_insight="Partial match",
            recommended_action="Action",
        )
        assert match.match_label == "Partial match"