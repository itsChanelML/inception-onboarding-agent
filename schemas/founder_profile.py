"""
schemas/founder_profile.py

Pydantic schema for founder profiles.
Validates intake data, enforces required fields, and provides
typed access to all profile attributes.

Used by:
  - tools/founder_db.py (validation on write)
  - agents/orchestrator.py (typed founder object)
  - app.py POST /api/onboard (intake validation)
  - agents/onboarding_agent.py (profile construction)

Usage:
    from schemas.founder_profile import FounderProfile, FundingStage

    # Validate raw dict from JSON
    profile = FounderProfile(**founder_dict)

    # Access typed fields
    print(profile.founder_name)
    print(profile.compliance_requirements)

    # Serialize back to dict for storage
    data = profile.model_dump()

    # Serialize to JSON
    json_str = profile.model_dump_json()
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class FundingStage(str, Enum):
    BOOTSTRAPPED = "Bootstrapped"
    PRE_SEED     = "Pre-seed"
    SEED         = "Seed"
    SERIES_A     = "Series A"
    SERIES_B     = "Series B"
    BEYOND       = "Series B+"


class DeploymentTarget(str, Enum):
    CLOUD      = "cloud"
    ON_PREMISE = "on-premise"
    HYBRID     = "hybrid"
    EDGE       = "edge"
    UNKNOWN    = "unknown"


class ComplianceRequirement(str, Enum):
    HIPAA   = "HIPAA"
    SOC2    = "SOC 2"
    FEDRAMP = "FedRAMP"
    GDPR    = "GDPR"
    FDA     = "FDA 510(k)"
    OSHA    = "OSHA"
    ISO     = "ISO 45001"
    NONE    = "No specific requirements"


class ProgramStage(str, Enum):
    IDEA      = "idea"
    PROTOTYPE = "prototype"
    MVP       = "mvp"
    EARLY_PROD = "early_production"
    PRODUCTION = "production"
    SCALE     = "scale"


# ── Main schema ───────────────────────────────────────────────────────────────

class FounderProfile(BaseModel):
    """
    Complete founder profile schema.

    Required fields are the minimum needed to generate a Vision
    Translation Brief and 12-Month Roadmap.

    Optional fields are populated progressively through onboarding
    and updated as the founder's journey progresses.
    """

    # ── Identity (required) ───────────────────────────────────────────────────
    founder_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full name of the founder"
    )
    company: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Company or product name"
    )
    domain: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Industry domain (e.g. medical imaging, precision agriculture)"
    )

    # ── Product (required) ────────────────────────────────────────────────────
    primary_challenge: str = Field(
        ...,
        min_length=10,
        description="The founder's primary technical or business challenge"
    )
    deployment_target: str = Field(
        ...,
        description="Where the product runs: cloud, on-premise, hybrid, or edge"
    )
    twelve_month_goal: str = Field(
        ...,
        min_length=10,
        description="What success looks like in 12 months"
    )

    # ── Technical (optional, populated through onboarding) ────────────────────
    product: Optional[str] = Field(
        None,
        description="One-sentence product description"
    )
    current_stack: list[str] = Field(
        default_factory=list,
        description="Current technical stack (frameworks, tools, languages)"
    )
    nvidia_tools: list[str] = Field(
        default_factory=list,
        description="NVIDIA tools in use or recommended"
    )
    compliance_requirements: list[str] = Field(
        default_factory=list,
        description="Regulatory or compliance requirements (HIPAA, SOC 2, etc.)"
    )

    # ── Business (optional) ───────────────────────────────────────────────────
    funding_stage: Optional[str] = Field(
        None,
        description="Current funding stage"
    )
    investor_narrative: Optional[str] = Field(
        None,
        description="The investor story — why this is defensible at scale"
    )
    team_size: Optional[str] = Field(
        None,
        description="Team size description (solo, 2-5, 6+)"
    )
    target_customer: Optional[str] = Field(
        None,
        description="First paying customer profile"
    )

    # ── Program metadata (set by system) ─────────────────────────────────────
    inception_group: Optional[str] = Field(
        None,
        description="Inception program group (e.g. Group 4 — Domain GenAI)"
    )
    join_date: Optional[str] = Field(
        None,
        description="ISO date when founder joined the program"
    )
    manager_name: Optional[str] = Field(
        None,
        description="Assigned DevRel manager name"
    )
    program_stage: Optional[str] = Field(
        None,
        description="Current program stage (prototype, mvp, production, etc.)"
    )
    version: int = Field(
        default=1,
        description="Profile version — increments on each update"
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("founder_name")
    @classmethod
    def name_must_have_space(cls, v: str) -> str:
        """Warn if founder name appears to be missing a last name."""
        if " " not in v.strip():
            # Not an error — some founders go by one name
            pass
        return v.strip()

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("current_stack", "nvidia_tools", "compliance_requirements", mode="before")
    @classmethod
    def ensure_list(cls, v) -> list:
        """Accept either a list or a comma-separated string."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v or []

    @field_validator("deployment_target")
    @classmethod
    def normalize_deployment(cls, v: str) -> str:
        v = v.lower()
        if "premise" in v or "on-prem" in v:
            return "on-premise"
        if "hybrid" in v:
            return "hybrid"
        if "edge" in v or "drone" in v or "embedded" in v:
            return "edge"
        if "cloud" in v:
            return "cloud"
        return v

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def first_name(self) -> str:
        """Returns the founder's first name."""
        return self.founder_name.split()[0]

    @property
    def is_healthcare(self) -> bool:
        """Returns True if the founder is in a healthcare domain."""
        healthcare_keywords = ["medical", "health", "clinical", "hospital", "radiology",
                               "genomic", "ophthalmology", "pharma", "biotech"]
        return any(kw in self.domain.lower() for kw in healthcare_keywords)

    @property
    def needs_hipaa(self) -> bool:
        """Returns True if HIPAA compliance is required."""
        return "HIPAA" in self.compliance_requirements

    @property
    def is_edge_deployment(self) -> bool:
        return "edge" in self.deployment_target.lower()

    @property
    def has_nvidia_stack(self) -> bool:
        return len(self.nvidia_tools) > 0

    @property
    def stack_summary(self) -> str:
        """Returns a readable summary of the NVIDIA stack."""
        if not self.nvidia_tools:
            return "No NVIDIA tools specified"
        return " · ".join(self.nvidia_tools)

    # ── Serialization helpers ─────────────────────────────────────────────────

    def to_prompt_context(self) -> str:
        """
        Returns a compact string representation for injection into NIM prompts.
        More readable than raw JSON for system prompts.
        """
        lines = [
            f"Founder: {self.founder_name}",
            f"Company: {self.company}",
            f"Domain: {self.domain}",
            f"Primary challenge: {self.primary_challenge}",
            f"Deployment: {self.deployment_target}",
            f"12-month goal: {self.twelve_month_goal}",
        ]
        if self.nvidia_tools:
            lines.append(f"NVIDIA stack: {self.stack_summary}")
        if self.compliance_requirements:
            lines.append(f"Compliance: {', '.join(self.compliance_requirements)}")
        if self.funding_stage:
            lines.append(f"Funding: {self.funding_stage}")
        if self.team_size:
            lines.append(f"Team: {self.team_size}")
        return "\n".join(lines)

    def bumped_version(self) -> "FounderProfile":
        """Returns a copy of this profile with version incremented."""
        data = self.model_dump()
        data["version"] = self.version + 1
        return FounderProfile(**data)

    class Config:
        # Allow extra fields from legacy JSON files that predate this schema
        extra = "allow"
        str_strip_whitespace = True