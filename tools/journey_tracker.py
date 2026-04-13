"""
tools/journey_tracker.py

Instruments the founder journey — tracking milestone velocity,
tool adoption, Aria engagement, and cohort comparisons.

This is the data layer that powers:
  - Manager portal health signals (on track / watch / at risk)
  - Morning scan (monitor_agent.py)
  - Pattern matching (pattern_matcher.py)
  - Portfolio overview stats

Features:
  - Record milestone events (started, updated, completed)
  - Track tool adoption (which NVIDIA tools are being used)
  - Track Aria session activity
  - Calculate days active, velocity, cohort position
  - Generate health signals per founder

Usage:
    from tools.journey_tracker import JourneyTracker

    tracker = JourneyTracker("claravision")

    # Record a milestone update
    tracker.update_milestone(3, pct=40, note="Egress policy configured")

    # Record milestone completion
    tracker.complete_milestone(2)

    # Record an Aria session
    tracker.record_aria_session(turns=6, topic="NIM egress policy")

    # Record tool adoption
    tracker.record_tool_adoption("NVIDIA FLARE")

    # Get health signal
    signal = tracker.health_signal()
    # Returns: {"status": "watch", "reason": "...", "score": 62}

    # Get cohort position
    position = tracker.cohort_position(all_trackers)
"""

import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

JOURNEY_DIR = Path("outputs/journeys")

# Health signal thresholds
HEALTH_ON_TRACK = "on_track"
HEALTH_WATCH    = "watch"
HEALTH_AT_RISK  = "at_risk"

# Scoring weights for health calculation
WEIGHT_MILESTONE_VELOCITY  = 0.40
WEIGHT_ARIA_ENGAGEMENT     = 0.25
WEIGHT_TOOL_ADOPTION       = 0.20
WEIGHT_TICKET_RESOLUTION   = 0.15

# Expected milestone completion rates by day
# Key: day of program, Value: expected milestone number
COHORT_PACE = {
    7:  1,
    14: 2,
    21: 2,
    30: 3,
    45: 4,
    60: 4,
    90: 5,
}

# Days without Aria activity before flagging
ARIA_SILENCE_THRESHOLD = 7


# ── JourneyTracker ────────────────────────────────────────────────────────────

class JourneyTracker:
    """
    Tracks and instruments a single founder's journey through
    the Inception program.

    Data is persisted to: outputs/journeys/<slug>_journey.json
    """

    def __init__(self, slug: str):
        self.slug = slug
        JOURNEY_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing journey or initialize fresh
        self._data = self._load()

    # ── Milestone tracking ────────────────────────────────────────────────────

    def update_milestone(
        self,
        milestone_id: int,
        pct:          int,
        note:         Optional[str] = None,
    ) -> None:
        """
        Record a milestone progress update.
        pct: 0-100 completion percentage.
        """
        event = {
            "type":         "milestone_update",
            "milestone_id": milestone_id,
            "pct":          pct,
            "note":         note,
            "timestamp":    _now(),
        }
        self._data["events"].append(event)

        # Update milestone state
        ms = self._get_or_create_milestone(milestone_id)
        ms["pct"]         = pct
        ms["last_updated"] = _now()
        if ms["started_at"] is None:
            ms["started_at"] = _now()

        self._save()

    def complete_milestone(
        self,
        milestone_id: int,
        note:         Optional[str] = None,
    ) -> None:
        """Record a milestone as complete (100%)."""
        event = {
            "type":         "milestone_complete",
            "milestone_id": milestone_id,
            "note":         note,
            "timestamp":    _now(),
        }
        self._data["events"].append(event)

        ms = self._get_or_create_milestone(milestone_id)
        ms["pct"]          = 100
        ms["status"]       = "complete"
        ms["completed_at"] = _now()
        if ms["started_at"] is None:
            ms["started_at"] = _now()

        # Track streak
        self._data["milestones_completed"] = self.milestones_completed_count()
        self._save()

    def get_milestone(self, milestone_id: int) -> Optional[dict]:
        """Returns state for a specific milestone."""
        for ms in self._data["milestones"]:
            if ms["id"] == milestone_id:
                return ms
        return None

    def current_milestone(self) -> Optional[dict]:
        """Returns the currently active (in-progress) milestone."""
        for ms in sorted(self._data["milestones"], key=lambda m: m["id"]):
            if ms["status"] == "active":
                return ms
        return None

    def milestones_completed_count(self) -> int:
        return sum(1 for ms in self._data["milestones"] if ms["status"] == "complete")

    def latest_milestone_pct(self) -> int:
        """Returns the completion % of the current active milestone."""
        ms = self.current_milestone()
        return ms["pct"] if ms else 0

    # ── Aria engagement ───────────────────────────────────────────────────────

    def record_aria_session(
        self,
        turns:  int,
        topic:  Optional[str] = None,
    ) -> None:
        """Record an Aria chat session."""
        event = {
            "type":      "aria_session",
            "turns":     turns,
            "topic":     topic,
            "timestamp": _now(),
        }
        self._data["events"].append(event)
        self._data["aria_sessions"].append({
            "turns":     turns,
            "topic":     topic,
            "timestamp": _now(),
        })
        self._data["total_aria_turns"] = self.total_aria_turns()
        self._save()

    def total_aria_sessions(self) -> int:
        return len(self._data["aria_sessions"])

    def total_aria_turns(self) -> int:
        return sum(s["turns"] for s in self._data["aria_sessions"])

    def days_since_last_aria_session(self) -> Optional[int]:
        """Returns days since the last Aria session, or None if no sessions."""
        sessions = self._data["aria_sessions"]
        if not sessions:
            return None
        last = sessions[-1]["timestamp"]
        last_date = datetime.fromisoformat(last).date()
        return (date.today() - last_date).days

    def aria_silent(self) -> bool:
        """Returns True if there's been no Aria activity in ARIA_SILENCE_THRESHOLD days."""
        days = self.days_since_last_aria_session()
        if days is None:
            return True
        return days >= ARIA_SILENCE_THRESHOLD

    # ── Tool adoption ─────────────────────────────────────────────────────────

    def record_tool_adoption(self, tool_name: str) -> None:
        """Record that a founder has started using a specific NVIDIA tool."""
        if tool_name not in self._data["tools_adopted"]:
            self._data["tools_adopted"].append(tool_name)
            self._data["events"].append({
                "type":      "tool_adopted",
                "tool":      tool_name,
                "timestamp": _now(),
            })
            self._save()

    def tools_adopted(self) -> list[str]:
        return self._data["tools_adopted"]

    def tool_adoption_rate(self, recommended_tools: list[str]) -> float:
        """
        Returns the fraction of recommended tools that have been adopted.
        0.0 = none adopted, 1.0 = all adopted.
        """
        if not recommended_tools:
            return 0.0
        adopted = set(self._data["tools_adopted"])
        recommended = set(recommended_tools)
        return len(adopted & recommended) / len(recommended)

    # ── Ticket tracking ───────────────────────────────────────────────────────

    def record_ticket(self, ticket_id: str, urgency: str) -> None:
        """Record a submitted support ticket."""
        self._data["tickets"].append({
            "ticket_id": ticket_id,
            "urgency":   urgency,
            "status":    "open",
            "submitted": _now(),
        })
        self._save()

    def record_ticket_resolved(self, ticket_id: str) -> None:
        """Mark a ticket as resolved."""
        for ticket in self._data["tickets"]:
            if ticket["ticket_id"] == ticket_id:
                ticket["status"]   = "resolved"
                ticket["resolved"] = _now()
        self._save()

    def open_tickets(self) -> list[dict]:
        return [t for t in self._data["tickets"] if t["status"] == "open"]

    def urgent_open_tickets(self) -> list[dict]:
        return [t for t in self.open_tickets() if t.get("urgency") == "urgent"]

    # ── Days active ───────────────────────────────────────────────────────────

    def days_active(self) -> int:
        """Returns number of days since the founder joined."""
        joined = self._data.get("joined_at")
        if not joined:
            return 0
        joined_date = datetime.fromisoformat(joined).date()
        return (date.today() - joined_date).days

    def set_join_date(self, iso_date: Optional[str] = None) -> None:
        """Set or reset the founder's join date. Defaults to today."""
        self._data["joined_at"] = iso_date or _now()
        self._save()

    # ── Health signal ─────────────────────────────────────────────────────────

    def health_signal(self, recommended_tools: Optional[list] = None) -> dict:
        """
        Calculate a health signal for this founder.

        Returns:
        {
            "status": "on_track" | "watch" | "at_risk",
            "score":  int (0-100),
            "reason": str,
            "flags":  list of specific issues
        }
        """
        flags  = []
        scores = {}

        # 1. Milestone velocity score
        days   = self.days_active()
        completed = self.milestones_completed_count()
        expected  = _expected_milestones(days)
        if expected > 0:
            velocity_score = min(100, int((completed / expected) * 100))
        else:
            velocity_score = 100
        scores["velocity"] = velocity_score

        if completed < expected:
            flags.append(f"Behind on milestones — {completed} complete, {expected} expected at Day {days}")

        # 2. Aria engagement score
        aria_sessions = self.total_aria_sessions()
        if aria_sessions == 0:
            aria_score = 0
            flags.append("No Aria sessions recorded")
        elif self.aria_silent():
            days_silent = self.days_since_last_aria_session()
            aria_score  = max(0, 60 - (days_silent * 5))
            flags.append(f"No Aria activity in {days_silent} days")
        else:
            aria_score = min(100, aria_sessions * 15)
        scores["aria"] = aria_score

        # 3. Tool adoption score
        if recommended_tools:
            adoption_rate = self.tool_adoption_rate(recommended_tools)
            tool_score    = int(adoption_rate * 100)
            if tool_score < 50:
                flags.append(f"Low tool adoption — {int(adoption_rate * 100)}% of recommended NVIDIA tools in use")
        else:
            tool_score = 70   # Neutral if no tools specified
        scores["tools"] = tool_score

        # 4. Ticket pressure score (urgent open tickets reduce score)
        urgent = len(self.urgent_open_tickets())
        ticket_score = max(0, 100 - (urgent * 25))
        if urgent > 0:
            flags.append(f"{urgent} urgent open ticket{'s' if urgent > 1 else ''}")
        scores["tickets"] = ticket_score

        # Weighted composite score
        composite = int(
            scores["velocity"] * WEIGHT_MILESTONE_VELOCITY +
            scores["aria"]     * WEIGHT_ARIA_ENGAGEMENT    +
            scores["tools"]    * WEIGHT_TOOL_ADOPTION      +
            scores["tickets"]  * WEIGHT_TICKET_RESOLUTION
        )

        # Determine status
        if composite >= 70 and not flags:
            status = HEALTH_ON_TRACK
            reason = f"Day {days} · {completed} milestones complete · Aria engagement healthy"
        elif composite >= 45 or len(flags) <= 1:
            status = HEALTH_WATCH
            reason = flags[0] if flags else f"Composite score {composite} — monitoring"
        else:
            status = HEALTH_AT_RISK
            reason = f"{len(flags)} risk signals — immediate attention recommended"

        return {
            "status":    status,
            "score":     composite,
            "reason":    reason,
            "flags":     flags,
            "scores":    scores,
            "days_active": days,
        }

    # ── Cohort comparison ─────────────────────────────────────────────────────

    def cohort_position(self, all_trackers: list["JourneyTracker"]) -> dict:
        """
        Compare this founder's progress to all others in the cohort.

        Args:
            all_trackers: List of JourneyTracker instances for all founders.

        Returns dict with:
            - rank: int (1 = fastest)
            - total: int
            - ahead_of_pct: float (percentage of cohort this founder is ahead of)
            - weeks_ahead: float (weeks ahead/behind cohort average)
        """
        if not all_trackers:
            return {"rank": 1, "total": 1, "ahead_of_pct": 100.0, "weeks_ahead": 0.0}

        # Sort all trackers by milestones completed desc, then by days active asc
        sorted_trackers = sorted(
            all_trackers,
            key=lambda t: (-t.milestones_completed_count(), t.days_active())
        )

        rank  = next(
            (i + 1 for i, t in enumerate(sorted_trackers) if t.slug == self.slug),
            len(sorted_trackers)
        )
        total = len(sorted_trackers)
        ahead_of_pct = round((total - rank) / total * 100, 1)

        # Weeks ahead of average
        avg_completed = sum(t.milestones_completed_count() for t in all_trackers) / total
        my_completed  = self.milestones_completed_count()
        weeks_ahead   = round((my_completed - avg_completed) * 2, 1)  # ~2 weeks per milestone

        return {
            "rank":         rank,
            "total":        total,
            "ahead_of_pct": ahead_of_pct,
            "weeks_ahead":  weeks_ahead,
        }

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns full journey data as a dict."""
        return dict(self._data)

    def summary(self) -> dict:
        """Returns a lightweight summary for portfolio views."""
        return {
            "slug":                self.slug,
            "days_active":         self.days_active(),
            "milestones_completed": self.milestones_completed_count(),
            "current_milestone_pct": self.latest_milestone_pct(),
            "aria_sessions":       self.total_aria_sessions(),
            "tools_adopted":       self.tools_adopted(),
            "open_tickets":        len(self.open_tickets()),
            "health":              self.health_signal()["status"],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        path = self._path()
        path.write_text(json.dumps(self._data, indent=2))

    def _load(self) -> dict:
        path = self._path()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return self._fresh()

    def _fresh(self) -> dict:
        """Returns a fresh journey data structure."""
        return {
            "slug":                self.slug,
            "joined_at":           _now(),
            "milestones":          [],
            "milestones_completed": 0,
            "aria_sessions":       [],
            "total_aria_turns":    0,
            "tools_adopted":       [],
            "tickets":             [],
            "events":              [],
        }

    def _path(self) -> Path:
        return JOURNEY_DIR / f"{self.slug}_journey.json"

    def _get_or_create_milestone(self, milestone_id: int) -> dict:
        for ms in self._data["milestones"]:
            if ms["id"] == milestone_id:
                return ms
        ms = {
            "id":           milestone_id,
            "status":       "active",
            "pct":          0,
            "started_at":   None,
            "completed_at": None,
            "last_updated": None,
        }
        self._data["milestones"].append(ms)
        return ms


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def _expected_milestones(days_active: int) -> int:
    """Returns the expected number of completed milestones for a given day."""
    expected = 0
    for day, milestone in sorted(COHORT_PACE.items()):
        if days_active >= day:
            expected = milestone
    return expected


def load_all_trackers(slugs: list[str]) -> list[JourneyTracker]:
    """Load JourneyTracker instances for a list of founder slugs."""
    return [JourneyTracker(slug) for slug in slugs]