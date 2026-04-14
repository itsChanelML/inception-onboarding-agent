"""
agents/monitor_agent.py

Morning portfolio health scan. Runs once per day (or on demand)
and produces a prioritized action list for the manager.

What it does:
  1. Loads all founder profiles
  2. Runs health signals via JourneyTracker
  3. Checks for Aria silence (no sessions in 7+ days)
  4. Checks for unactivated benefits
  5. Checks for open urgent tickets
  6. Runs pattern matching for at-risk founders
  7. Uses NIM to generate a morning briefing summary
  8. Returns a structured report the manager portal can render

Called by:
  - app.py GET /api/morning-scan
  - Can be scheduled via APScheduler for automated daily runs

Usage:
    from agents.monitor_agent import MonitorAgent

    agent = MonitorAgent()

    # Run the full morning scan
    report = agent.run()

    print(report["summary"])           # NIM-generated briefing
    print(report["priority_actions"])  # Ordered list of actions
    print(report["at_risk"])           # Founders needing immediate attention
    print(report["on_track"])          # Founders progressing well
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from tools.nim_client import NIMClient, NANO
from tools.founder_db import FounderDB
from tools.journey_tracker import JourneyTracker, load_all_trackers
from agents.pattern_matcher import PatternMatcher

# ── Constants ─────────────────────────────────────────────────────────────────

OUTPUTS_DIR = Path("outputs")

SYSTEM_MORNING_BRIEFING = (
    "You are an AI advisor briefing an NVIDIA Inception DevRel manager at the start of their day. "
    "Be direct. Prioritize ruthlessly. Name specific founders and specific actions. "
    "No preamble. Under 120 words."
)

# Benefit activation check
BENEFITS_TO_CHECK = [
    ("google_cloud_credits", "Google Cloud Credits ($350K)"),
    ("anthropic_credits",    "Anthropic Claude API ($1M)"),
    ("aws_credits",          "AWS Activate ($100K)"),
]

# Days since join before flagging unactivated benefits
BENEFIT_ACTIVATION_SLA_DAYS = 14


# ── MonitorAgent ──────────────────────────────────────────────────────────────

class MonitorAgent:
    """
    Runs a daily portfolio health scan and produces a prioritized
    action report for the manager.
    """

    def __init__(
        self,
        nim_client:      Optional[NIMClient] = None,
        founder_db:      Optional[FounderDB] = None,
        pattern_matcher: Optional[PatternMatcher] = None,
    ):
        self.nim     = nim_client      or NIMClient()
        self.db      = founder_db      or FounderDB()
        self.matcher = pattern_matcher or PatternMatcher(nim_client=self.nim)

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, manager_name: str = "Chanel") -> dict:
        """
        Run the full morning portfolio scan.

        Returns a structured report dict:
        {
            "generated_at":    ISO timestamp,
            "manager_name":    str,
            "summary":         str (NIM-generated briefing),
            "priority_actions": list of action dicts,
            "at_risk":         list of founder signal dicts,
            "watch":           list of founder signal dicts,
            "on_track":        list of founder signal dicts,
            "portfolio_stats": dict,
            "errors":          list of error strings,
        }
        """
        report = {
            "generated_at":    datetime.now().isoformat(),
            "manager_name":    manager_name,
            "summary":         "",
            "priority_actions": [],
            "at_risk":         [],
            "watch":           [],
            "on_track":        [],
            "portfolio_stats": {},
            "errors":          [],
        }

        # 1. Load all founders
        try:
            founders = self.db.get_all()
        except Exception as e:
            report["errors"].append(f"Could not load founders: {e}")
            return report

        if not founders:
            report["summary"] = "No active founders in portfolio."
            return report

        slugs    = [f["_slug"] for f in founders if "_slug" in f]
        trackers = load_all_trackers(slugs)

        # 2. Scan each founder
        all_signals      = []
        priority_actions = []

        for founder, tracker in zip(founders, trackers):
            try:
                signal = self._scan_founder(founder, tracker, trackers)
                all_signals.append(signal)

                # Bucket by health status
                status = signal["health"]["status"]
                if status == "at_risk":
                    report["at_risk"].append(signal)
                elif status == "watch":
                    report["watch"].append(signal)
                else:
                    report["on_track"].append(signal)

                # Collect priority actions
                for action in signal.get("actions", []):
                    priority_actions.append({
                        "priority":     action["priority"],
                        "founder_name": founder.get("founder_name", "Unknown"),
                        "company":      founder.get("company", ""),
                        "action":       action["action"],
                        "reason":       action["reason"],
                    })

            except Exception as e:
                report["errors"].append(
                    f"Error scanning {founder.get('company', 'unknown')}: {e}"
                )

        # 3. Sort priority actions by priority (1 = most urgent)
        priority_actions.sort(key=lambda x: x["priority"])
        report["priority_actions"] = priority_actions[:10]  # Top 10

        # 4. Portfolio stats
        report["portfolio_stats"] = self._portfolio_stats(founders, trackers, all_signals)

        # 5. Generate NIM morning briefing
        report["summary"] = self._generate_briefing(
            manager_name, report, all_signals
        )

        # 6. Save report to disk
        self._save_report(report)

        return report

    # ── Founder scan ──────────────────────────────────────────────────────────

    def _scan_founder(
        self,
        founder:      dict,
        tracker:      JourneyTracker,
        all_trackers: list[JourneyTracker],
    ) -> dict:
        """
        Scan a single founder and return their signal dict.
        """
        slug         = founder.get("_slug", "unknown")
        founder_name = founder.get("founder_name", "Unknown")
        company      = founder.get("company", "Unknown")

        # Health signal
        recommended_tools = founder.get("nvidia_tools", [])
        health = tracker.health_signal(recommended_tools=recommended_tools)

        # Cohort position
        cohort = tracker.cohort_position(all_trackers)

        # Specific checks
        actions = []

        # Check: first meeting pending
        days_active = tracker.days_active()
        if days_active >= 7 and tracker.total_aria_sessions() == 0:
            actions.append({
                "priority": 1,
                "action":   f"Schedule kickoff call with {founder_name}",
                "reason":   f"Day {days_active} with no Aria activity — first meeting overdue",
            })

        # Check: Aria silence
        if tracker.aria_silent() and days_active > 7:
            days_silent = tracker.days_since_last_aria_session() or days_active
            actions.append({
                "priority": 2,
                "action":   f"Proactive outreach to {founder_name}",
                "reason":   f"No Aria activity in {days_silent} days — possible disengagement",
            })

        # Check: unactivated benefits
        benefit_flags = self._check_benefits(founder, days_active)
        for flag in benefit_flags:
            actions.append({
                "priority": 3,
                "action":   f"Nudge {founder_name} to activate {flag}",
                "reason":   f"Benefits unactivated at Day {days_active} — missed program value",
            })

        # Check: urgent open tickets
        urgent_tickets = tracker.urgent_open_tickets()
        if urgent_tickets:
            actions.append({
                "priority": 1,
                "action":   f"Reply to urgent ticket from {founder_name}",
                "reason":   f"{len(urgent_tickets)} urgent ticket(s) open",
            })

        # Check: milestone stall
        ms_pct = tracker.latest_milestone_pct()
        if 0 < ms_pct < 30 and days_active > 21:
            actions.append({
                "priority": 2,
                "action":   f"Check in on {company} milestone progress",
                "reason":   f"Active milestone at {ms_pct}% after Day {days_active}",
            })

        # Pattern match for at-risk founders
        pattern_insight = None
        if health["status"] in ("at_risk", "watch"):
            try:
                match = self.matcher.best_match(founder)
                if match and match.similarity_score >= 0.55:
                    pattern_insight = match.key_insight
                    actions.append({
                        "priority": 2,
                        "action":   match.recommended_action,
                        "reason":   f"Pattern match: {match.similarity_pct}% similar to successful {match.pattern.domain} founder",
                    })
            except Exception:
                pass

        return {
            "slug":            slug,
            "founder_name":    founder_name,
            "company":         company,
            "domain":          founder.get("domain", ""),
            "days_active":     days_active,
            "health":          health,
            "cohort":          cohort,
            "pattern_insight": pattern_insight,
            "actions":         actions,
            "milestones_done": tracker.milestones_completed_count(),
            "aria_sessions":   tracker.total_aria_sessions(),
            "open_tickets":    len(tracker.open_tickets()),
        }

    # ── Benefit checking ──────────────────────────────────────────────────────

    def _check_benefits(self, founder: dict, days_active: int) -> list[str]:
        """
        Returns list of unactivated benefit names.
        Only flags after BENEFIT_ACTIVATION_SLA_DAYS.
        """
        if days_active < BENEFIT_ACTIVATION_SLA_DAYS:
            return []

        unactivated = []

        # Check Google Cloud credits
        if not founder.get("google_cloud_activated", False):
            unactivated.append("Google Cloud Credits ($350K)")

        # Check Anthropic credits
        if not founder.get("anthropic_activated", False):
            unactivated.append("Anthropic API Credits ($1M)")

        return unactivated

    # ── Portfolio stats ───────────────────────────────────────────────────────

    def _portfolio_stats(
        self,
        founders:     list[dict],
        trackers:     list[JourneyTracker],
        all_signals:  list[dict],
    ) -> dict:
        """Compute portfolio-level statistics."""
        total = len(founders)
        if total == 0:
            return {}

        at_risk  = sum(1 for s in all_signals if s["health"]["status"] == "at_risk")
        watch    = sum(1 for s in all_signals if s["health"]["status"] == "watch")
        on_track = sum(1 for s in all_signals if s["health"]["status"] == "on_track")

        avg_milestones = (
            sum(t.milestones_completed_count() for t in trackers) / total
            if trackers else 0
        )
        avg_aria_sessions = (
            sum(t.total_aria_sessions() for t in trackers) / total
            if trackers else 0
        )
        total_open_tickets = sum(
            len(t.open_tickets()) for t in trackers
        )
        total_urgent = sum(
            len(t.urgent_open_tickets()) for t in trackers
        )

        return {
            "total_founders":       total,
            "at_risk":              at_risk,
            "watch":                watch,
            "on_track":             on_track,
            "avg_milestones":       round(avg_milestones, 1),
            "avg_aria_sessions":    round(avg_aria_sessions, 1),
            "open_tickets":         total_open_tickets,
            "urgent_tickets":       total_urgent,
            "health_score_avg":     round(
                sum(s["health"]["score"] for s in all_signals) / total
                if all_signals else 0, 1
            ),
        }

    # ── NIM briefing ──────────────────────────────────────────────────────────

    def _generate_briefing(
        self,
        manager_name: str,
        report:       dict,
        all_signals:  list[dict],
    ) -> str:
        """
        Use NIM to generate a concise morning briefing for the manager.
        Falls back to a rule-based summary if NIM call fails.
        """
        stats = report["portfolio_stats"]

        try:
            # Build context for NIM
            at_risk_names = [s["company"] for s in report["at_risk"]]
            watch_names   = [s["company"] for s in report["watch"]]
            top_actions   = report["priority_actions"][:3]

            prompt = (
                f"Manager: {manager_name}\n"
                f"Portfolio: {stats.get('total_founders', 0)} founders\n"
                f"At risk: {', '.join(at_risk_names) or 'none'}\n"
                f"Watch: {', '.join(watch_names) or 'none'}\n"
                f"Open tickets: {stats.get('open_tickets', 0)} "
                f"({stats.get('urgent_tickets', 0)} urgent)\n"
                f"Top 3 actions today:\n"
                + "\n".join(
                    f"  {i+1}. {a['action']} — {a['reason']}"
                    for i, a in enumerate(top_actions)
                ) +
                f"\n\nWrite the morning briefing. Start with the most urgent issue."
            )

            return self.nim.complete_fast(
                prompt=prompt,
                system=SYSTEM_MORNING_BRIEFING,
                max_tokens=180,
            ).strip()

        except Exception as e:
            print(f"[MonitorAgent] NIM briefing failed: {e}")
            return self._fallback_briefing(manager_name, report, stats)

    def _fallback_briefing(
        self,
        manager_name: str,
        report:       dict,
        stats:        dict,
    ) -> str:
        """Rule-based briefing when NIM is unavailable."""
        lines = [f"Good morning, {manager_name}."]

        if report["at_risk"]:
            names = ", ".join(s["company"] for s in report["at_risk"])
            lines.append(f"{len(report['at_risk'])} founder(s) at risk: {names}.")

        if stats.get("urgent_tickets", 0) > 0:
            lines.append(f"{stats['urgent_tickets']} urgent ticket(s) need your reply today.")

        if report["priority_actions"]:
            top = report["priority_actions"][0]
            lines.append(f"Top priority: {top['action']}.")

        lines.append(
            f"Portfolio health: {stats.get('on_track', 0)} on track, "
            f"{stats.get('watch', 0)} watch, {stats.get('at_risk', 0)} at risk."
        )

        return " ".join(lines)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_report(self, report: dict) -> str:
        """Save the morning scan report to disk."""
        import os
        if os.environ.get("VERCEL") == "1":
            return "vercel-readonly"
        try:
            OUTPUTS_DIR.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = OUTPUTS_DIR / f"morning_scan_{timestamp}.json"
            serializable = json.loads(json.dumps(report, default=str))
            path.write_text(json.dumps(serializable, indent=2))
            return str(path)
        except OSError:
            return "filesystem-readonly"

    def load_latest_report(self) -> Optional[dict]:
        """Load the most recent morning scan report from disk."""
        reports = sorted(OUTPUTS_DIR.glob("morning_scan_*.json"), reverse=True)
        if not reports:
            return None
        try:
            return json.loads(reports[0].read_text())
        except Exception:
            return None