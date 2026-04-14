"""
agents/pattern_matcher.py

Finds analogous successful founder journeys and surfaces relevant
lessons for the manager and Aria.

Given a current founder's profile, this agent:
  1. Scores each seed pattern against the founder's profile
  2. Returns the top N matches with similarity scores
  3. Extracts actionable insights from the matched patterns
  4. Uses NIM to generate a manager-facing recommendation

Called by:
  - app.py GET /api/patterns/<slug>
  - agents/orchestrator.py (included in full run)
  - agents/monitor_agent.py (morning scan enrichment)

Usage:
    from agents.pattern_matcher import PatternMatcher

    matcher = PatternMatcher()

    # Find matches for a founder
    matches = matcher.find_matches(founder_profile, top_n=3)

    # Get manager recommendation
    recommendation = matcher.manager_recommendation(founder_profile, matches)

    # Quick check — is there a strong match?
    best = matcher.best_match(founder_profile)
    if best and best.similarity_score >= 0.7:
        print(best.key_insight)
"""

import json
from typing import Optional

from tools.nim_client import NIMClient, NANO
from schemas.journey import JourneyPattern, PatternMatch, SimilarityDimension, SEED_PATTERNS

# ── Constants ─────────────────────────────────────────────────────────────────

STRONG_MATCH_THRESHOLD  = 0.75
GOOD_MATCH_THRESHOLD    = 0.55
WEAK_MATCH_THRESHOLD    = 0.35

# Scoring weights per similarity dimension
DIMENSION_WEIGHTS = {
    SimilarityDimension.DOMAIN:            0.30,
    SimilarityDimension.DEPLOYMENT_TARGET: 0.20,
    SimilarityDimension.COMPLIANCE:        0.20,
    SimilarityDimension.NVIDIA_TOOLS:      0.15,
    SimilarityDimension.PRIMARY_CHALLENGE: 0.10,
    SimilarityDimension.FUNDING_STAGE:     0.05,
}

SYSTEM_INSIGHT_GENERATOR = (
    "You are an NVIDIA Inception program advisor. "
    "Given a current founder's profile and analogous successful founder journeys, "
    "generate a specific, actionable insight for the manager. "
    "Be concrete. Reference the specific unlock that worked for the analogous founder. "
    "Under 60 words."
)


# ── PatternMatcher ────────────────────────────────────────────────────────────

class PatternMatcher:
    """
    Matches a current founder against historical journey patterns
    to surface relevant lessons and recommended actions.
    """

    def __init__(
        self,
        nim_client: Optional[NIMClient] = None,
        patterns:   Optional[list[JourneyPattern]] = None,
    ):
        self.nim      = nim_client or NIMClient()
        self.patterns = patterns or SEED_PATTERNS

    # ── Main interface ────────────────────────────────────────────────────────

    def find_matches(
        self,
        founder:  dict,
        top_n:    int = 3,
        min_score: float = WEAK_MATCH_THRESHOLD,
    ) -> list[PatternMatch]:
        """
        Find the top N most similar patterns for a founder.

        Args:
            founder:   Founder profile dict.
            top_n:     Maximum number of matches to return.
            min_score: Minimum similarity score to include (0.0 - 1.0).

        Returns:
            List of PatternMatch objects, sorted by similarity score desc.
        """
        scored = []

        for pattern in self.patterns:
            score, dimensions = self._score(founder, pattern)
            if score < min_score:
                continue

            insight, action = self._extract_insight(founder, pattern, score)

            match = PatternMatch(
                pattern=pattern,
                similarity_score=round(score, 2),
                matched_on=dimensions,
                key_insight=insight,
                recommended_action=action,
            )
            scored.append(match)

        scored.sort(key=lambda m: m.similarity_score, reverse=True)
        return scored[:top_n]

    def best_match(self, founder: dict) -> Optional[PatternMatch]:
        """Returns the single best matching pattern, or None if no strong match."""
        matches = self.find_matches(founder, top_n=1, min_score=WEAK_MATCH_THRESHOLD)
        return matches[0] if matches else None

    def manager_recommendation(
        self,
        founder: dict,
        matches: list[PatternMatch],
    ) -> str:
        """
        Use NIM to generate a manager-facing recommendation based on
        the top matched patterns.

        Returns a plain string recommendation under 150 words.
        Falls back to a rule-based recommendation if NIM call fails.
        """
        if not matches:
            return self._fallback_recommendation(founder)

        try:
            top = matches[0]
            prompt = (
                f"Current founder:\n"
                f"- Company: {founder.get('company', 'unknown')}\n"
                f"- Domain: {founder.get('domain', 'unknown')}\n"
                f"- Challenge: {founder.get('primary_challenge', 'not specified')}\n"
                f"- Deployment: {founder.get('deployment_target', 'not specified')}\n\n"
                f"Most analogous successful founder (similarity: {top.similarity_pct}%):\n"
                f"- Domain: {top.pattern.domain}\n"
                f"- Key unlock: {top.pattern.key_unlock}\n"
                f"- Outcome: {top.pattern.outcome_description}\n"
                f"- Manager actions that helped: {'; '.join(top.pattern.manager_actions_that_helped[:2])}\n\n"
                f"Generate a specific recommendation for this founder's manager. "
                f"What should they do THIS WEEK based on what worked for the analogous founder? "
                f"Be concrete. Under 80 words."
            )

            return self.nim.complete_fast(
                prompt=prompt,
                system=SYSTEM_INSIGHT_GENERATOR,
                max_tokens=150,
            ).strip()

        except Exception as e:
            print(f"[PatternMatcher] NIM recommendation failed: {e}")
            return self._fallback_recommendation(founder, matches[0] if matches else None)

    def lessons_for_aria(self, founder: dict, top_n: int = 2) -> str:
        """
        Returns relevant lessons formatted for injection into Aria's
        system prompt — so Aria can reference analogous founder experiences.
        """
        matches = self.find_matches(founder, top_n=top_n)
        if not matches:
            return ""

        lines = ["Relevant lessons from analogous successful founders:"]
        for match in matches:
            lines.append(f"\nAnalogous founder ({match.pattern.domain}, {match.similarity_pct}% similar):")
            for lesson in match.pattern.lessons[:2]:
                lines.append(f"  • {lesson}")

        return "\n".join(lines)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score(
        self,
        founder: dict,
        pattern: JourneyPattern,
    ) -> tuple[float, list[SimilarityDimension]]:
        """
        Score a pattern against a founder profile.

        Returns:
            (score: float 0.0-1.0, matched_dimensions: list)
        """
        total_score  = 0.0
        matched_dims = []

        # Domain similarity
        domain_score = self._domain_similarity(
            founder.get("domain", ""),
            pattern.domain
        )
        if domain_score > 0:
            total_score += domain_score * DIMENSION_WEIGHTS[SimilarityDimension.DOMAIN]
            matched_dims.append(SimilarityDimension.DOMAIN)

        # Deployment target
        deploy_score = self._exact_match(
            self._normalize_deploy(founder.get("deployment_target", "")),
            self._normalize_deploy(pattern.deployment_target),
        )
        if deploy_score > 0:
            total_score += deploy_score * DIMENSION_WEIGHTS[SimilarityDimension.DEPLOYMENT_TARGET]
            matched_dims.append(SimilarityDimension.DEPLOYMENT_TARGET)

        # Compliance requirements
        compliance_score = self._list_overlap(
            founder.get("compliance_requirements", []),
            pattern.compliance_requirements,
        )
        if compliance_score > 0:
            total_score += compliance_score * DIMENSION_WEIGHTS[SimilarityDimension.COMPLIANCE]
            matched_dims.append(SimilarityDimension.COMPLIANCE)

        # NVIDIA tools
        tools_score = self._list_overlap(
            founder.get("nvidia_tools", []),
            pattern.nvidia_tools,
        )
        if tools_score > 0:
            total_score += tools_score * DIMENSION_WEIGHTS[SimilarityDimension.NVIDIA_TOOLS]
            matched_dims.append(SimilarityDimension.NVIDIA_TOOLS)

        # Primary challenge — keyword overlap
        challenge_score = self._keyword_overlap(
            founder.get("primary_challenge", ""),
            pattern.primary_challenge,
        )
        if challenge_score > 0:
            total_score += challenge_score * DIMENSION_WEIGHTS[SimilarityDimension.PRIMARY_CHALLENGE]
            matched_dims.append(SimilarityDimension.PRIMARY_CHALLENGE)

        # Funding stage
        funding_score = self._exact_match(
            founder.get("funding_stage", ""),
            pattern.funding_stage_at_join or "",
        )
        if funding_score > 0:
            total_score += funding_score * DIMENSION_WEIGHTS[SimilarityDimension.FUNDING_STAGE]
            matched_dims.append(SimilarityDimension.FUNDING_STAGE)

        return min(total_score, 1.0), matched_dims

    # ── Insight extraction ────────────────────────────────────────────────────

    def _extract_insight(
        self,
        founder: dict,
        pattern: JourneyPattern,
        score:   float,
    ) -> tuple[str, str]:
        """
        Extract a key insight and recommended action from a pattern match.
        Rule-based — no NIM call for speed.

        Returns:
            (key_insight: str, recommended_action: str)
        """
        insight = (
            f"{int(score * 100)}% match with a successful {pattern.domain} founder. "
            f"Key unlock: {pattern.key_unlock[:120]}"
        )

        # Pick the most relevant manager action
        if pattern.manager_actions_that_helped:
            action = pattern.manager_actions_that_helped[0]
        elif pattern.lessons:
            action = pattern.lessons[0]
        else:
            action = f"Apply lessons from analogous {pattern.domain} deployment."

        return insight, action

    def _fallback_recommendation(
        self,
        founder:  dict,
        match:    Optional[PatternMatch] = None,
    ) -> str:
        """Rule-based fallback when NIM is unavailable."""
        company = founder.get("company", "this founder")
        if match:
            return (
                f"Based on analogous {match.pattern.domain} founders: "
                f"{match.pattern.key_unlock}. "
                f"Recommended action: {match.recommended_action}"
            )
        return (
            f"No strong pattern match found for {company}. "
            f"Focus on activating partner benefits and scheduling the first kickoff call."
        )

    # ── Similarity helpers ────────────────────────────────────────────────────

    @staticmethod
    def _domain_similarity(domain_a: str, domain_b: str) -> float:
        """
        Score domain similarity.
        Exact match = 1.0, shared keyword = 0.5, no match = 0.0.
        """
        a = domain_a.lower().strip()
        b = domain_b.lower().strip()

        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        # Keyword overlap
        words_a = set(a.split())
        words_b = set(b.split())
        overlap = words_a & words_b

        # Domain category groups
        healthcare = {"medical", "health", "clinical", "hospital", "radiology",
                      "genomic", "ophthalmology", "imaging", "pharma", "biotech"}
        edge       = {"edge", "drone", "robotics", "agriculture", "construction",
                      "manufacturing", "jetson", "embedded"}
        nlp        = {"nlp", "language", "speech", "voice", "text", "clinical nlp"}

        def category(words: set) -> Optional[str]:
            if words & healthcare:
                return "healthcare"
            if words & edge:
                return "edge"
            if words & nlp:
                return "nlp"
            return None

        cat_a = category(words_a)
        cat_b = category(words_b)

        if cat_a and cat_a == cat_b:
            return 0.7   # Same category, different domain
        if overlap:
            return 0.4   # Shared keyword

        return 0.0

    @staticmethod
    def _exact_match(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return 1.0 if a.lower().strip() == b.lower().strip() else 0.0

    @staticmethod
    def _list_overlap(list_a: list, list_b: list) -> float:
        """Jaccard similarity between two lists."""
        if not list_a or not list_b:
            return 0.0
        set_a = {item.lower() for item in list_a}
        set_b = {item.lower() for item in list_b}
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _keyword_overlap(text_a: str, text_b: str) -> float:
        """Keyword overlap between two text strings."""
        if not text_a or not text_b:
            return 0.0
        stop_words = {"the", "a", "an", "is", "are", "was", "for", "to",
                      "of", "in", "on", "at", "and", "or", "but", "with"}
        words_a = {w.lower() for w in text_a.split() if w.lower() not in stop_words}
        words_b = {w.lower() for w in text_b.split() if w.lower() not in stop_words}
        if not words_a or not words_b:
            return 0.0
        overlap = words_a & words_b
        return len(overlap) / max(len(words_a), len(words_b))

    @staticmethod
    def _normalize_deploy(target: str) -> str:
        t = target.lower()
        if "premise" in t or "on-prem" in t:
            return "on-premise"
        if "hybrid" in t:
            return "hybrid"
        if "edge" in t:
            return "edge"
        if "cloud" in t:
            return "cloud"
        return t.strip()