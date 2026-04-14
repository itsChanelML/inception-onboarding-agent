"""
agents/onboarding_agent.py

Handles the conversational onboarding flow for new founders.

Two responsibilities:
  1. Chip prediction — given partial profile + next question,
     predict 3-4 likely answers using NIM (NANO model for speed)

  2. Profile construction — takes completed onboarding answers,
     validates them against FounderProfile schema, and saves
     the profile via FounderDB

Called by:
  - app.py POST /api/onboard/predict-chips
  - app.py POST /api/onboard

The 13 onboarding questions are defined here as the canonical source
of truth. The frontend renders them — this file owns the logic.

Usage:
    from agents.onboarding_agent import OnboardingAgent

    agent = OnboardingAgent()

    # Predict chips for question 3 given what we know so far
    chips = agent.predict_chips(
        partial_profile={"vision": "medical imaging AI", "target_user": "radiologists"},
        next_question="Tell me where the technology actually is today.",
        n=4
    )

    # Process completed onboarding and save profile
    result = agent.process_intake(slug="claravision_new", answers=answers_dict)
"""

import json
import re
import unicodedata
from typing import Optional

from tools.nim_client import NIMClient, NANO, SUPER
from tools.founder_db import FounderDB
from schemas.founder_profile import FounderProfile

# ── Constants ─────────────────────────────────────────────────────────────────

SYSTEM_CHIP_PREDICTOR = (
    "You are predicting likely answers a startup founder would give to an onboarding question. "
    "Return ONLY a JSON array of 3-4 short strings. Each under 12 words. "
    "Make them specific to the founder's context. No markdown, no explanation."
)

SYSTEM_PROFILE_SYNTHESIZER = (
    "You are an NVIDIA Inception program advisor synthesizing a founder's onboarding answers "
    "into a structured profile. Be specific. Use the founder's exact words where possible. "
    "Return ONLY valid JSON matching the requested structure."
)

# ── The 13 onboarding questions ───────────────────────────────────────────────
# These are the canonical questions. The frontend renders them.
# This list is used for validation and ordering.

ONBOARDING_QUESTIONS = [
    # Chapter 1 — Vision (3 questions)
    {
        "id":      "q1",
        "chapter": "vision",
        "field":   "vision",
        "question": "Let's start with the big picture. What are you building — in your own words, not the pitch version?",
        "default_chips": [
            "An AI model that solves a specific industry problem",
            "A platform connecting AI capabilities to enterprise workflows",
            "A hardware-accelerated solution for real-time processing",
            "Something else — I'll describe it myself",
        ],
        "multi": False,
    },
    {
        "id":      "q2",
        "chapter": "vision",
        "field":   "target_user",
        "question": "Got it. Who is this for — who wakes up with the problem you're solving?",
        "default_chips": [
            "Clinical or medical professionals",
            "Industrial or manufacturing operators",
            "Developers or technical teams",
            "Enterprise business decision makers",
        ],
        "multi": False,
    },
    {
        "id":      "q3",
        "chapter": "vision",
        "field":   "success_definition",
        "question": "What does winning look like for you — not for the company, for you personally — 12 months from now?",
        "default_chips": [
            "My product is deployed and being used by real customers",
            "I've raised my next funding round",
            "My team executes the vision without me in every decision",
            "I've proven the technology works at production scale",
        ],
        "multi": False,
    },

    # Chapter 2 — Technical (4 questions)
    {
        "id":      "q4",
        "chapter": "technical",
        "field":   "product_stage",
        "question": "Tell me where the technology actually is today — not where you want it to be.",
        "default_chips": [
            "I have an idea and early research but nothing built yet",
            "I have a working prototype on my local machine",
            "I have an MVP that a small group has tested",
            "I have a product in early production with real users",
        ],
        "multi": False,
    },
    {
        "id":      "q5",
        "chapter": "technical",
        "field":   "current_stack",
        "question": "What does your current technical stack look like? Select all that apply.",
        "default_chips": [
            "PyTorch",
            "TensorFlow",
            "JAX",
            "Hugging Face",
            "MONAI",
            "Custom architecture",
        ],
        "multi": True,
    },
    {
        "id":      "q6",
        "chapter": "technical",
        "field":   "deployment_target",
        "question": "Where does your product need to run — who controls the infrastructure?",
        "default_chips": [
            "In a public cloud — AWS, GCP, or Azure",
            "On the customer's own servers — fully on-premise",
            "A hybrid of cloud and on-premise",
            "At the edge — on a device, drone, or embedded system",
        ],
        "multi": False,
    },
    {
        "id":      "q7",
        "chapter": "technical",
        "field":   "compliance",
        "question": "Are there any compliance or regulatory requirements in your space? Select all that apply.",
        "default_chips": [
            "HIPAA — healthcare data",
            "SOC 2 — enterprise security",
            "FedRAMP — government",
            "GDPR — European data",
            "No specific requirements",
        ],
        "multi": True,
    },

    # Chapter 3 — Team (2 questions)
    {
        "id":      "q8",
        "chapter": "team",
        "field":   "team_size",
        "question": "Who's building this with you?",
        "default_chips": [
            "Just me right now — solo founder",
            "Me and a co-founder",
            "Small team — 3 to 5 people",
            "Larger team — 6 or more",
        ],
        "multi": False,
    },
    {
        "id":      "q9",
        "chapter": "team",
        "field":   "cto_background",
        "question": "Where does technical decision-making live on your team?",
        "default_chips": [
            "I make the technical decisions — I'm the technical founder",
            "My CTO or lead engineer leads technical direction",
            "We decide together — it's collaborative",
            "I have a technical advisor but no full-time technical lead",
        ],
        "multi": False,
    },

    # Chapter 4 — Market (3 questions)
    {
        "id":      "q10",
        "chapter": "market",
        "field":   "first_customer",
        "question": "Who is your first paying customer — or who should be?",
        "default_chips": [
            "A hospital or healthcare system",
            "An enterprise company in my industry",
            "A government agency or public institution",
            "A developer or technical team",
        ],
        "multi": False,
    },
    {
        "id":      "q11",
        "chapter": "market",
        "field":   "funding_stage",
        "question": "Where are you on funding?",
        "default_chips": [
            "Bootstrapped — self-funded, no outside investment",
            "Pre-seed — friends, family, or angels",
            "Seed round — institutional investors",
            "Series A or beyond",
        ],
        "multi": False,
    },
    {
        "id":      "q12",
        "chapter": "market",
        "field":   "twelve_month_goal",
        "question": "What's your 12-month revenue goal — give me a number or a range, even a rough one.",
        "default_chips": [],   # No chips — open text only
        "multi": False,
    },

    # Chapter 5 — Ask (1 question)
    {
        "id":      "q13",
        "chapter": "ask",
        "field":   "primary_ask",
        "question": "Last one. What do you need most from this program right now — be honest, there's no wrong answer.",
        "default_chips": [
            "Technical help — I'm stuck on architecture or deployment",
            "Validation — I need to know if my approach is right",
            "Connections — introductions to customers, partners, or investors",
            "Visibility — co-marketing, press, or showcase opportunities",
            "Credits and infrastructure — I need GPU access to move faster",
        ],
        "multi": False,
    },
]

# Map question IDs to their index for quick lookup
QUESTION_INDEX = {q["id"]: q for q in ONBOARDING_QUESTIONS}


# ── OnboardingAgent ───────────────────────────────────────────────────────────

class OnboardingAgent:
    """
    Manages the conversational onboarding flow.
    Uses NANO model for chip prediction (speed matters in real-time UI).
    Uses SUPER model for profile synthesis (quality matters for downstream agents).
    """

    def __init__(self, nim_client: Optional[NIMClient] = None):
        self.nim = nim_client or NIMClient()
        self.db  = FounderDB()

    # ── Chip prediction ───────────────────────────────────────────────────────

    def predict_chips(
        self,
        partial_profile: dict,
        next_question:   str,
        n:               int = 4,
    ) -> list[str]:
        """
        Predict likely answer chips for the next onboarding question.

        Uses the NANO model for sub-2-second response time.
        Falls back to empty list (frontend uses hardcoded defaults) on failure.

        Args:
            partial_profile: Answers collected so far in the onboarding.
            next_question:   The question text being asked next.
            n:               Number of chips to generate (max 4).

        Returns:
            List of short strings, each under 12 words.
        """
        if not partial_profile:
            return []

        context = self._profile_to_context(partial_profile)

        prompt = (
            f"Founder context so far:\n{context}\n\n"
            f"Next question: \"{next_question}\"\n\n"
            f"Generate {min(n, 4)} specific, likely answers this founder would give. "
            f"Each answer must be under 12 words. "
            f"Return ONLY a JSON array of strings."
        )

        try:
            result = self.nim.complete_json(
                prompt=prompt,
                system=SYSTEM_CHIP_PREDICTOR,
                model=NANO,
                max_tokens=200,
            )

            if isinstance(result, list):
                # Clean and truncate each chip
                chips = [self._clean_chip(c) for c in result if isinstance(c, str)]
                return chips[:n]

        except Exception as e:
            print(f"[OnboardingAgent] Chip prediction failed: {e}")

        return []

    def get_question(self, question_id: str) -> Optional[dict]:
        """Returns a question definition by ID."""
        return QUESTION_INDEX.get(question_id)

    def get_all_questions(self) -> list[dict]:
        """Returns all 13 onboarding questions in order."""
        return ONBOARDING_QUESTIONS

    def get_chapter_questions(self, chapter: str) -> list[dict]:
        """Returns questions for a specific chapter."""
        return [q for q in ONBOARDING_QUESTIONS if q["chapter"] == chapter]

    # ── Profile construction ──────────────────────────────────────────────────

    def process_intake(
        self,
        slug:    str,
        answers: dict,
        founder_name: Optional[str] = None,
        company:      Optional[str] = None,
    ) -> dict:
        """
        Process completed onboarding answers into a validated founder profile.

        Steps:
          1. Map raw answers to FounderProfile fields
          2. Use NIM to synthesize a clean primary_challenge from answers
          3. Validate against FounderProfile schema
          4. Save to FounderDB
          5. Return the saved profile dict

        Args:
            slug:         URL-safe founder identifier (e.g. "claravision_2")
            answers:      Dict of field -> answer from the onboarding flow
            founder_name: Override if not in answers dict
            company:      Override if not in answers dict

        Returns:
            The validated and saved founder profile dict.
        """
        # Build raw profile from answers
        raw = dict(answers)
        if founder_name:
            raw["founder_name"] = founder_name
        if company:
            raw["company"] = company

        # Synthesize primary_challenge if not explicitly provided
        if not raw.get("primary_challenge"):
            raw["primary_challenge"] = self._synthesize_challenge(raw)

        # Synthesize investor_narrative
        if not raw.get("investor_narrative"):
            raw["investor_narrative"] = self._synthesize_narrative(raw)

        # Map answer fields to FounderProfile fields
        profile_data = self._map_answers_to_profile(raw)

        # Validate with Pydantic
        try:
            profile = FounderProfile(**profile_data)
        except Exception as e:
            # If validation fails, save raw data anyway with a flag
            print(f"[OnboardingAgent] Profile validation warning for {slug}: {e}")
            profile_data["_validation_warning"] = str(e)
            self.db.save(slug, profile_data, validate=False)
            return profile_data

        # Save validated profile
        saved = self.db.save(slug, profile.model_dump())
        return saved

    # ── NIM synthesis helpers ─────────────────────────────────────────────────

    def _synthesize_challenge(self, answers: dict) -> str:
        """
        Use NIM to synthesize a primary_challenge from onboarding answers.
        Falls back to a constructed string if NIM call fails.
        """
        try:
            context = self._profile_to_context(answers)
            prompt  = (
                f"Based on these founder onboarding answers:\n{context}\n\n"
                f"Write ONE sentence describing their primary technical or business challenge. "
                f"Be specific. Under 25 words. Start with the challenge, not the founder."
            )
            return self.nim.complete_fast(prompt, max_tokens=80).strip()
        except Exception:
            # Fallback: construct from available fields
            parts = []
            if answers.get("deployment_target"):
                parts.append(f"{answers['deployment_target']} deployment")
            if answers.get("compliance"):
                parts.append(f"{answers['compliance']} compliance")
            if answers.get("vision"):
                parts.append(f"for {answers['vision']}")
            return " ".join(parts) if parts else "Technical architecture and go-to-market execution."

    def _synthesize_narrative(self, answers: dict) -> str:
        """
        Use NIM to synthesize an investor narrative from onboarding answers.
        """
        try:
            context = self._profile_to_context(answers)
            prompt  = (
                f"Based on these founder onboarding answers:\n{context}\n\n"
                f"Write ONE sentence investor narrative — why this product is defensible at scale. "
                f"Under 20 words. Make it specific to their domain and deployment approach."
            )
            return self.nim.complete_fast(prompt, max_tokens=60).strip()
        except Exception:
            return f"Building defensible AI infrastructure in {answers.get('domain', 'a focused domain')}."

    # ── Field mapping ─────────────────────────────────────────────────────────

    def _map_answers_to_profile(self, answers: dict) -> dict:
        """
        Map onboarding answer keys to FounderProfile field names.
        Handles both direct matches and renamed fields.
        """
        field_map = {
            "vision":            "product",
            "target_user":       "target_customer",
            "success_definition": None,   # Informational only
            "product_stage":     "program_stage",
            "compliance":        "compliance_requirements",
            "cto_background":    None,    # Stored in primary_challenge context
            "first_customer":    "target_customer",
            "primary_ask":       None,    # Stored in primary_challenge context
        }

        profile = {}
        for key, value in answers.items():
            if key.startswith("_"):
                continue
            mapped_key = field_map.get(key, key)   # Use field_map or keep original
            if mapped_key is not None:
                profile[mapped_key] = value

        # Ensure required fields have values
        profile.setdefault("domain", answers.get("vision", "AI"))
        profile.setdefault("deployment_target", answers.get("deployment_target", "cloud"))
        profile.setdefault("twelve_month_goal", answers.get("twelve_month_goal", "Scale the product"))

        return profile

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _profile_to_context(profile: dict) -> str:
        """Converts a partial profile dict to a readable context string."""
        lines = []
        label_map = {
            "vision":            "Building",
            "target_user":       "For",
            "product_stage":     "Stage",
            "current_stack":     "Stack",
            "deployment_target": "Deployment",
            "compliance":        "Compliance",
            "team_size":         "Team",
            "funding_stage":     "Funding",
            "twelve_month_goal": "12-month goal",
            "primary_ask":       "Needs most",
            "domain":            "Domain",
            "company":           "Company",
            "founder_name":      "Founder",
        }
        for key, label in label_map.items():
            val = profile.get(key)
            if val:
                if isinstance(val, list):
                    val = ", ".join(val)
                lines.append(f"{label}: {val}")
        return "\n".join(lines) if lines else "No context yet."

    @staticmethod
    def _clean_chip(text: str) -> str:
        """Normalize and truncate a chip string."""
        # Normalize unicode
        text = unicodedata.normalize("NFKC", text).strip()
        # Remove leading bullets or numbers
        text = re.sub(r"^[\d\.\-\*\•]\s*", "", text)
        # Truncate to ~12 words
        words = text.split()
        if len(words) > 14:
            text = " ".join(words[:12]) + "..."
        return text