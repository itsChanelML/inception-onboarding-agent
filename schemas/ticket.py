"""
schemas/ticket.py

Pydantic schema for support tickets.
Defines ticket structure, routing rules, and status transitions.

Used by:
  - agents/ticket_agent.py
  - app.py POST /api/tickets

Usage:
    from schemas.ticket import Ticket, TicketStatus, TicketCategory, TicketUrgency

    ticket = Ticket(
        founder_slug="claravision",
        question="How do I configure NIM egress policy on GKE?",
        category=TicketCategory.TECHNICAL,
        urgency=TicketUrgency.URGENT,
    )

    print(ticket.needs_human)     # True (urgent tickets route to human)
    print(ticket.routing_label)   # "Manager — Urgent"
"""

from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import uuid


# ── Enums ─────────────────────────────────────────────────────────────────────

class TicketStatus(str, Enum):
    OPEN       = "open"
    ARIA_DRAFT = "aria_draft"   # Aria has drafted a response, manager to review
    PENDING    = "pending"      # Waiting for manager review
    RESOLVED   = "resolved"
    CLOSED     = "closed"


class TicketCategory(str, Enum):
    TECHNICAL   = "technical"
    PARTNERSHIP = "partnership"
    COMPLIANCE  = "compliance"
    BILLING     = "billing"
    GENERAL     = "general"


class TicketUrgency(str, Enum):
    URGENT   = "urgent"
    MODERATE = "moderate"
    GENERAL  = "general"


class RoutingPreference(str, Enum):
    HUMAN  = "human"    # Founder wants a human reply
    ARIA   = "aria"     # Aria response is fine
    EITHER = "either"   # No preference


# ── Routing rules ─────────────────────────────────────────────────────────────

# These rules determine whether a ticket should go to a human manager
# or can be handled by Aria alone.
ROUTING_RULES = {
    # Always route to human
    (TicketCategory.PARTNERSHIP, TicketUrgency.URGENT):   "manager",
    (TicketCategory.COMPLIANCE,  TicketUrgency.URGENT):   "manager",
    (TicketCategory.TECHNICAL,   TicketUrgency.URGENT):   "manager",
    (TicketCategory.BILLING,     TicketUrgency.URGENT):   "manager",

    # Aria can handle with manager review
    (TicketCategory.TECHNICAL,   TicketUrgency.MODERATE): "aria_then_manager",
    (TicketCategory.COMPLIANCE,  TicketUrgency.MODERATE): "aria_then_manager",
    (TicketCategory.PARTNERSHIP, TicketUrgency.MODERATE): "manager",

    # Aria can handle independently
    (TicketCategory.TECHNICAL,   TicketUrgency.GENERAL):  "aria",
    (TicketCategory.GENERAL,     TicketUrgency.GENERAL):  "aria",
    (TicketCategory.BILLING,     TicketUrgency.GENERAL):  "aria_then_manager",
}

DEFAULT_ROUTING = "aria_then_manager"


# ── Ticket ────────────────────────────────────────────────────────────────────

class Ticket(BaseModel):
    """
    A support ticket submitted by a founder.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    ticket_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())[:8].upper(),
        description="Short unique ticket ID"
    )
    founder_slug: str = Field(..., description="Founder slug (e.g. claravision)")
    founder_name: Optional[str] = Field(None, description="Founder display name")

    # ── Content ───────────────────────────────────────────────────────────────
    question: str = Field(
        ...,
        min_length=10,
        description="The founder's question or issue description"
    )
    category: TicketCategory = Field(
        default=TicketCategory.GENERAL,
        description="Ticket category"
    )
    urgency: TicketUrgency = Field(
        default=TicketUrgency.GENERAL,
        description="Urgency level"
    )
    routing_preference: RoutingPreference = Field(
        default=RoutingPreference.EITHER,
        description="Founder's preferred response channel"
    )

    # ── Aria response ─────────────────────────────────────────────────────────
    aria_draft: Optional[str] = Field(
        None,
        description="Aria's drafted response — manager reviews before sending"
    )
    aria_confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Aria's confidence in the draft (0.0 - 1.0)"
    )
    aria_triage_reason: Optional[str] = Field(
        None,
        description="Aria's one-sentence explanation of the classification"
    )

    # ── Manager response ──────────────────────────────────────────────────────
    manager_reply: Optional[str] = Field(
        None,
        description="Final reply sent to the founder"
    )
    manager_name: Optional[str] = Field(
        None,
        description="Manager who handled the ticket"
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status: TicketStatus = Field(
        default=TicketStatus.OPEN,
        description="Current ticket status"
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    submitted_at:  str = Field(default_factory=lambda: datetime.now().isoformat())
    resolved_at:   Optional[str] = None
    last_updated:  Optional[str] = None

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        return v.strip()

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def routing(self) -> str:
        """
        Returns the recommended routing for this ticket.
        One of: manager | aria_then_manager | aria
        """
        # Founder explicitly requested human
        if self.routing_preference == RoutingPreference.HUMAN:
            return "manager"

        rule = ROUTING_RULES.get((self.category, self.urgency), DEFAULT_ROUTING)
        return rule

    @property
    def needs_human(self) -> bool:
        """Returns True if this ticket should be reviewed by a human manager."""
        return self.routing in ("manager", "aria_then_manager")

    @property
    def aria_can_handle(self) -> bool:
        """Returns True if Aria can respond without manager review."""
        return self.routing == "aria"

    @property
    def routing_label(self) -> str:
        """Human-readable routing label for the manager portal."""
        labels = {
            "manager":          f"Manager — {self.urgency.value.title()}",
            "aria_then_manager": "Aria Draft · Manager Review",
            "aria":             "Aria · Auto-resolve",
        }
        return labels.get(self.routing, "Manager Review")

    @property
    def is_open(self) -> bool:
        return self.status in (TicketStatus.OPEN, TicketStatus.ARIA_DRAFT, TicketStatus.PENDING)

    @property
    def is_resolved(self) -> bool:
        return self.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)

    @property
    def age_hours(self) -> float:
        """Returns how many hours since the ticket was submitted."""
        submitted = datetime.fromisoformat(self.submitted_at)
        delta = datetime.now() - submitted
        return round(delta.total_seconds() / 3600, 1)

    @property
    def is_overdue(self) -> bool:
        """
        Returns True if the ticket has exceeded expected response time.
        Urgent: 2 hours. Moderate: 8 hours. General: 24 hours.
        """
        sla = {
            TicketUrgency.URGENT:   2,
            TicketUrgency.MODERATE: 8,
            TicketUrgency.GENERAL:  24,
        }
        return self.is_open and self.age_hours > sla.get(self.urgency, 24)

    # ── Status transitions ────────────────────────────────────────────────────

    def with_aria_draft(self, draft: str, confidence: float = 0.8) -> "Ticket":
        """Returns a copy with Aria's draft attached."""
        data = self.model_dump()
        data["aria_draft"]      = draft
        data["aria_confidence"] = confidence
        data["status"]          = TicketStatus.ARIA_DRAFT
        data["last_updated"]    = datetime.now().isoformat()
        return Ticket(**data)

    def with_resolution(self, reply: str, manager: Optional[str] = None) -> "Ticket":
        """Returns a copy marked as resolved with the manager's reply."""
        data = self.model_dump()
        data["manager_reply"] = reply
        data["manager_name"]  = manager
        data["status"]        = TicketStatus.RESOLVED
        data["resolved_at"]   = datetime.now().isoformat()
        data["last_updated"]  = datetime.now().isoformat()
        return Ticket(**data)

    class Config:
        extra = "allow"