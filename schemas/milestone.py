"""
schemas/milestone.py

Pydantic schema for program milestones.
Defines the structure of a milestone and its sub-tasks.

Used by:
  - tools/journey_tracker.py
  - agents/roadmap_agent.py
  - app.py GET/POST /api/founders/<slug>/milestones

Usage:
    from schemas.milestone import Milestone, MilestoneStatus, SubTask

    ms = Milestone(
        id=3,
        title="Compliance Architecture",
        description="HIPAA-compliant data flow documented...",
        month_range="Month 2-3",
        nvidia_tools=["NIM On-Prem", "NVIDIA FLARE"],
        status=MilestoneStatus.ACTIVE,
        pct=40,
    )

    print(ms.is_complete)   # False
    print(ms.is_active)     # True
"""

from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class MilestoneStatus(str, Enum):
    LOCKED   = "locked"
    ACTIVE   = "active"
    COMPLETE = "complete"


# ── SubTask ───────────────────────────────────────────────────────────────────

class SubTask(BaseModel):
    """A single checkable sub-task within a milestone."""

    id:          str
    title:       str
    complete:    bool = False
    completed_at: Optional[str] = None

    def mark_complete(self) -> "SubTask":
        return SubTask(
            id=self.id,
            title=self.title,
            complete=True,
            completed_at=datetime.now().isoformat(),
        )


# ── Milestone ─────────────────────────────────────────────────────────────────

class Milestone(BaseModel):
    """
    A single program milestone in the founder's 12-month roadmap.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id: int = Field(..., ge=1, le=7, description="Milestone number 1-7")
    title: str = Field(..., min_length=3, description="Short milestone title")
    description: str = Field(..., description="Full milestone description")
    month_range: str = Field(..., description="e.g. 'Month 1', 'Month 2-3'")

    # ── NVIDIA context ────────────────────────────────────────────────────────
    nvidia_tools: list[str] = Field(
        default_factory=list,
        description="NVIDIA tools used in this milestone"
    )
    deliverables: list[str] = Field(
        default_factory=list,
        description="Concrete deliverables for this milestone"
    )
    sub_tasks: list[SubTask] = Field(
        default_factory=list,
        description="Checkable sub-tasks within this milestone"
    )

    # ── Progress ──────────────────────────────────────────────────────────────
    status: MilestoneStatus = Field(
        default=MilestoneStatus.LOCKED,
        description="Current status"
    )
    pct: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Completion percentage 0-100"
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    started_at:   Optional[str] = None
    completed_at: Optional[str] = None
    last_updated: Optional[str] = None

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("pct")
    @classmethod
    def pct_triggers_status(cls, v: int) -> int:
        return v

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        return self.status == MilestoneStatus.COMPLETE or self.pct == 100

    @property
    def is_active(self) -> bool:
        return self.status == MilestoneStatus.ACTIVE

    @property
    def is_locked(self) -> bool:
        return self.status == MilestoneStatus.LOCKED

    @property
    def sub_tasks_complete(self) -> int:
        return sum(1 for t in self.sub_tasks if t.complete)

    @property
    def sub_tasks_total(self) -> int:
        return len(self.sub_tasks)

    @property
    def sub_task_pct(self) -> int:
        if not self.sub_tasks:
            return self.pct
        return int(self.sub_tasks_complete / self.sub_tasks_total * 100)

    def unlock(self) -> "Milestone":
        """Returns a copy of this milestone with status set to active."""
        data = self.model_dump()
        data["status"] = MilestoneStatus.ACTIVE
        data["started_at"] = datetime.now().isoformat()
        return Milestone(**data)

    def complete(self) -> "Milestone":
        """Returns a copy of this milestone marked complete."""
        data = self.model_dump()
        data["status"]       = MilestoneStatus.COMPLETE
        data["pct"]          = 100
        data["completed_at"] = datetime.now().isoformat()
        return Milestone(**data)

    class Config:
        extra = "allow"


# ── Default milestone templates ───────────────────────────────────────────────
# Used by roadmap_agent to populate a founder's roadmap from their profile.

MILESTONE_TEMPLATES = [
    {
        "id": 1,
        "title": "Infrastructure Foundation",
        "description": "Core NVIDIA infrastructure configured and running. Cloud credits activated.",
        "month_range": "Month 1",
        "deliverables": [
            "NIM microservices running",
            "Cloud credits activated",
            "Development environment configured",
            "First model inference test successful",
        ],
    },
    {
        "id": 2,
        "title": "Vision Translation Brief Generated",
        "description": "Aria maps founder vision to NVIDIA stack. CTO brief delivered. Manager briefed.",
        "month_range": "Month 1",
        "deliverables": [
            "Vision Translation Brief completed",
            "CTO Alignment Brief delivered",
            "Manager kickoff meeting scheduled",
            "12-Month Roadmap finalized",
        ],
    },
    {
        "id": 3,
        "title": "Core Architecture Complete",
        "description": "Primary technical architecture validated. Compliance requirements addressed.",
        "month_range": "Month 2-3",
        "deliverables": [
            "Architecture documented",
            "Compliance requirements addressed",
            "First integration test passing",
            "Performance benchmarks established",
        ],
    },
    {
        "id": 4,
        "title": "First Validation Run",
        "description": "Model or product tested on real or anonymized data. Results documented.",
        "month_range": "Month 4-5",
        "deliverables": [
            "Test dataset prepared",
            "Validation run completed",
            "Performance benchmarks documented",
            "Results formatted for stakeholder review",
        ],
    },
    {
        "id": 5,
        "title": "Evidence Package",
        "description": "Validation results formatted for customer or investor conversations.",
        "month_range": "Month 6-7",
        "deliverables": [
            "Technical evidence package complete",
            "NVIDIA co-marketing initiated",
            "Investor readiness materials drafted",
            "Inception Capital Connect introduction requested",
        ],
    },
    {
        "id": 6,
        "title": "First Customer or Partner Readiness",
        "description": "Product ready for first paying customer or signed partnership.",
        "month_range": "Month 8-9",
        "deliverables": [
            "Customer-facing documentation complete",
            "Onboarding process documented",
            "First warm VC or customer introduction made",
            "Pricing and commercial terms defined",
        ],
    },
    {
        "id": 7,
        "title": "12-Month Goal Achieved",
        "description": "Founder's stated 12-month goal reached.",
        "month_range": "Month 12",
        "deliverables": [
            "12-month goal milestone reached",
            "Next phase roadmap defined",
            "NVIDIA Inception alumni status achieved",
            "Program outcomes documented for co-marketing",
        ],
    },
]


def default_milestones() -> list[Milestone]:
    """
    Returns the 7 default milestone templates as Milestone objects.
    Used when generating a new founder roadmap.
    """
    milestones = []
    for i, template in enumerate(MILESTONE_TEMPLATES):
        status = MilestoneStatus.ACTIVE if i < 2 else MilestoneStatus.LOCKED
        ms = Milestone(**template, status=status)
        milestones.append(ms)
    return milestones