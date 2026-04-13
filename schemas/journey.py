"""
schemas/journey.py

Pydantic schema for founder journey success patterns.
Used by pattern_matcher.py to find analogous successful founders
and surface relevant lessons for the manager and Aria.

A JourneyPattern represents a distilled, anonymized record of a
successful founder journey — what they built, what blocked them,
what unlocked progress, and what the outcome was.

Usage:
    from schemas.journey import JourneyPattern, JourneyOutcome

    pattern = JourneyPattern(
        pattern_id="healthcare-nim-onprem-01",
        domain="medical imaging",
        deployment_target="on-premise",
        primary_challenge="HIPAA compliance architecture",
        nvidia_tools=["NIM", "Clara", "MONAI", "FLARE"],
        key_unlock="NIM self-hosted containers resolved compliance blocker in week 3",
        milestone_velocity=2.1,
        outcome=JourneyOutcome.PARTNERSHIP_SIGNED,
        outcome_description="First hospital partnership signed at Month 8",
        days_to_milestone_3=45,
        lessons=["Deploy NIM before finalizing compliance docs", "FLARE intro at Month 2 accelerated investor conversations"],
    )
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class JourneyOutcome(str, Enum):
    PARTNERSHIP_SIGNED  = "partnership_signed"
    FUNDING_RAISED      = "funding_raised"
    PRODUCT_LAUNCHED    = "product_launched"
    PILOT_COMPLETED     = "pilot_completed"
    SERIES_A            = "series_a"
    CO_MARKETING        = "co_marketing"
    STILL_IN_PROGRAM    = "still_in_program"
    CHURNED             = "churned"


class SimilarityDimension(str, Enum):
    """Dimensions along which two founder journeys can be similar."""
    DOMAIN             = "domain"
    DEPLOYMENT_TARGET  = "deployment_target"
    COMPLIANCE         = "compliance"
    NVIDIA_TOOLS       = "nvidia_tools"
    PRIMARY_CHALLENGE  = "primary_challenge"
    FUNDING_STAGE      = "funding_stage"
    TEAM_SIZE          = "team_size"


# ── JourneyPattern ────────────────────────────────────────────────────────────

class JourneyPattern(BaseModel):
    """
    Anonymized record of a successful (or unsuccessful) founder journey.
    Used by pattern_matcher.py to surface relevant analogies.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    pattern_id: str = Field(..., description="Unique pattern identifier")
    domain: str = Field(..., description="Industry domain")
    deployment_target: str = Field(..., description="Deployment architecture")

    # ── Context ───────────────────────────────────────────────────────────────
    primary_challenge: str = Field(..., description="The main challenge this founder faced")
    nvidia_tools: list[str] = Field(default_factory=list, description="NVIDIA tools used")
    compliance_requirements: list[str] = Field(default_factory=list)
    funding_stage_at_join: Optional[str] = Field(None, description="Funding stage when they joined")
    team_size: Optional[str] = Field(None)

    # ── Journey data ──────────────────────────────────────────────────────────
    key_unlock: str = Field(
        ...,
        description="The single thing that unblocked the most progress"
    )
    primary_blocker: Optional[str] = Field(
        None,
        description="What slowed them down the most"
    )
    milestone_velocity: float = Field(
        ...,
        ge=0.0,
        description="Average milestones completed per month"
    )
    days_to_milestone_3: Optional[int] = Field(
        None,
        description="Days to complete Milestone 3 (compliance/architecture)"
    )
    days_to_first_customer: Optional[int] = Field(
        None,
        description="Days to first paying customer or signed partnership"
    )
    aria_sessions_total: Optional[int] = Field(
        None,
        description="Total Aria sessions throughout the program"
    )

    # ── Outcome ───────────────────────────────────────────────────────────────
    outcome: JourneyOutcome = Field(..., description="Program outcome")
    outcome_description: str = Field(..., description="One sentence describing the outcome")
    total_days_in_program: Optional[int] = Field(None)

    # ── Lessons ───────────────────────────────────────────────────────────────
    lessons: list[str] = Field(
        default_factory=list,
        description="Key lessons from this journey — surfaced to managers and Aria"
    )
    manager_actions_that_helped: list[str] = Field(
        default_factory=list,
        description="Specific manager actions that accelerated this founder"
    )

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def was_successful(self) -> bool:
        return self.outcome not in (JourneyOutcome.CHURNED, JourneyOutcome.STILL_IN_PROGRAM)

    @property
    def lessons_formatted(self) -> str:
        if not self.lessons:
            return "No lessons recorded."
        return "\n".join(f"• {lesson}" for lesson in self.lessons)

    class Config:
        extra = "allow"


# ── PatternMatch ──────────────────────────────────────────────────────────────

class PatternMatch(BaseModel):
    """
    The result of matching a current founder against historical patterns.
    Returned by pattern_matcher.py.
    """

    pattern:          JourneyPattern
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 similarity")
    matched_on:       list[SimilarityDimension] = Field(default_factory=list)
    key_insight:      str = Field(..., description="One sentence of actionable insight for the manager")
    recommended_action: str = Field(..., description="Specific action the manager should take")

    @property
    def similarity_pct(self) -> int:
        return int(self.similarity_score * 100)

    @property
    def match_label(self) -> str:
        if self.similarity_score >= 0.8:
            return "Strong match"
        if self.similarity_score >= 0.6:
            return "Good match"
        return "Partial match"

    class Config:
        extra = "allow"


# ── Seed patterns ─────────────────────────────────────────────────────────────
# Pre-built success patterns for the pattern matcher to use before
# real historical data accumulates.

SEED_PATTERNS = [
    JourneyPattern(
        pattern_id="healthcare-nim-onprem-01",
        domain="medical imaging",
        deployment_target="on-premise",
        primary_challenge="HIPAA-compliant deployment inside hospital security perimeter",
        nvidia_tools=["NIM", "Clara", "MONAI", "FLARE"],
        compliance_requirements=["HIPAA"],
        funding_stage_at_join="Seed",
        key_unlock="NIM self-hosted containers resolved the compliance blocker — framing it as 'compliant by architecture' unlocked the hospital procurement conversation",
        primary_blocker="CTO was building a cloud-first architecture that couldn't pass HIPAA audit",
        milestone_velocity=1.8,
        days_to_milestone_3=38,
        days_to_first_customer=210,
        aria_sessions_total=24,
        outcome=JourneyOutcome.PARTNERSHIP_SIGNED,
        outcome_description="First hospital partnership signed at Month 7, pilot expanded to 3 hospitals by Month 10",
        total_days_in_program=300,
        lessons=[
            "Introduce NIM on-premise in the first meeting — don't wait for the founder to ask",
            "The 'compliant by architecture' framing is the phrase that unlocks procurement",
            "FLARE introduction at Month 2 gave the investor story before it was needed at Month 6",
            "CTO alignment must be resolved before Month 3 or it compounds into a 6-week delay",
        ],
        manager_actions_that_helped=[
            "Introduced NVIDIA solutions engineer in week 1 — saved 4 weeks on compliance architecture",
            "Facilitated Inception Capital Connect intro at Milestone 5",
            "Drafted the 'compliant by architecture' investor one-liner with Aria",
        ]
    ),
    JourneyPattern(
        pattern_id="edge-ai-agriculture-01",
        domain="precision agriculture",
        deployment_target="edge",
        primary_challenge="Sub-100ms inference on Jetson Orin in low-connectivity rural environments",
        nvidia_tools=["Jetson Orin", "TAO Toolkit", "NIM", "DeepStream"],
        compliance_requirements=[],
        funding_stage_at_join="Pre-seed",
        key_unlock="Domain-specific subset training on TAO — stopped training on full dataset, split by disease type first",
        primary_blocker="Model accuracy degraded in low-light and high-humidity field conditions",
        milestone_velocity=2.4,
        days_to_milestone_3=28,
        days_to_first_customer=155,
        aria_sessions_total=31,
        outcome=JourneyOutcome.FUNDING_RAISED,
        outcome_description="Series A closed at Month 9, 200-farm network by Month 11",
        total_days_in_program=330,
        lessons=[
            "TAO subset training is the unlock for domain-specific edge models — mention it early",
            "First paying customer de-risks the Series A narrative dramatically — push for it at Milestone 4",
            "Edge deployment on Jetson is a co-marketing asset — flag for partner showcase at Milestone 5",
            "Connectivity-first design thinking separates deployable edge AI from prototype edge AI",
        ],
        manager_actions_that_helped=[
            "Flagged for Q2 Partner Showcase — drove 3 investor inbound inquiries",
            "Introduced to AgriTech VC network at Milestone 6",
            "Nudged Anthropic credit activation — used for agronomist dashboard NLP layer",
        ]
    ),
    JourneyPattern(
        pattern_id="clinical-nlp-riva-01",
        domain="clinical NLP",
        deployment_target="cloud",
        primary_challenge="Riva ASR word error rate on clinical terminology and background noise",
        nvidia_tools=["NeMo", "Riva", "NIM"],
        compliance_requirements=["HIPAA"],
        funding_stage_at_join="Seed",
        key_unlock="Pre-filtering audio for speech frequencies (80-8000Hz bandpass) before Riva submission — 18% WER reduction",
        primary_blocker="Generic ASR models underperform on clinical vocabulary by 15-25% WER",
        milestone_velocity=2.1,
        days_to_milestone_3=35,
        days_to_first_customer=180,
        aria_sessions_total=19,
        outcome=JourneyOutcome.PRODUCT_LAUNCHED,
        outcome_description="Product launched to 12 hospitals by Month 10, 10K clinical hours/month transcribed",
        total_days_in_program=310,
        lessons=[
            "NeMo fine-tuning on medical vocabulary is non-negotiable — generic models won't pass clinical review",
            "The audio pre-processing step is not in NVIDIA docs but is the biggest WER lever",
            "Hospital IT approval process takes 6-8 weeks — start it at Milestone 3, not Milestone 5",
        ],
        manager_actions_that_helped=[
            "Connected to NVIDIA Riva specialist for audio pre-processing guidance",
            "Facilitated EHR vendor introduction at Milestone 4",
        ]
    ),
]