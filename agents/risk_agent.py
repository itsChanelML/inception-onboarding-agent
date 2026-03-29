"""
agents/risk_agent.py

Scans a founder profile and returns structured risk signals.
Called by the orchestrator after loading the founder profile.

Each risk signal has:
  - severity: "high" | "medium" | "low"
  - title:    short label shown in the manager portal
  - description: one paragraph, specific to this founder
  - manager_action: what the manager should do about it

The NIM call uses the risk_analysis.txt prompt and returns JSON.
If JSON parsing fails, falls back to three hardcoded signals derived
from the founder profile without a NIM call.
"""

import os
import json
import re
from pathlib import Path
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL        = "nvidia/nemotron-super-49b-v1"

# Fallback severity rules applied without a NIM call
# Each entry: (field_to_check, value_that_triggers, severity, title, description_template, action_template)
RULE_BASED_SIGNALS = [
    {
        "check": lambda f: not f.get("compliance_requirements"),
        "severity": "low",
        "title": "No Compliance Requirements Stated",
        "description": "Founder did not specify compliance requirements. This may indicate they haven't mapped regulatory constraints yet, or operate in an unregulated domain.",
        "manager_action": "Ask directly in the first meeting: 'Who is your first customer and what compliance does their procurement team require?'"
    },
    {
        "check": lambda f: "CTO" in f.get("primary_challenge", "") or "engineering team" in f.get("primary_challenge", "").lower(),
        "severity": "high",
        "title": "CTO / Team Alignment Gap Detected",
        "description": "The primary challenge explicitly names an internal alignment gap between founder vision and engineering execution. This is the most expensive problem at the prototype stage.",
        "manager_action": "Probe this in the first 5 minutes. Ask: 'Has your CTO read the Vision Translation Brief? What was their reaction?'"
    },
    {
        "check": lambda f: f.get("funding_stage") in ["Pre-seed", "Bootstrapped"],
        "severity": "medium",
        "title": "Early-Stage Funding — Credits Not Yet Activated",
        "description": "Founder is pre-seed or bootstrapped. Benefits packages (cloud credits, DLI access) are often unactivated at this stage due to bandwidth constraints.",
        "manager_action": "Confirm in the first meeting that Google Cloud and Anthropic credits are activated. Both are zero-effort unlocks with immediate value."
    },
]


# ── Main function ─────────────────────────────────────────────────────────────

def analyze_risks(founder: dict, client: OpenAI = None) -> list:
    """
    Analyze a founder profile for risk signals.

    Args:
        founder: parsed founder JSON dict
        client:  optional OpenAI client pointed at NIM.
                 If None, falls back to rule-based analysis only.

    Returns:
        list of dicts, each with keys: severity, title, description, manager_action
    """
    # Try NIM-powered analysis first
    if client is not None:
        try:
            signals = _nim_analyze(founder, client)
            if signals:
                return signals
        except Exception as e:
            print(f"[RiskAgent] NIM call failed, falling back to rules: {e}")

    # Fallback: rule-based analysis
    return _rule_based_analyze(founder)


# ── NIM-powered analysis ──────────────────────────────────────────────────────

def _nim_analyze(founder: dict, client: OpenAI) -> list:
    """
    Call NIM with the risk_analysis prompt. Expects JSON back.
    Returns a list of signal dicts, or raises on failure.
    """
    prompt_path = Path("prompts/risk_analysis.txt")
    if not prompt_path.exists():
        raise FileNotFoundError("prompts/risk_analysis.txt not found")

    with open(prompt_path) as f:
        template = f.read()

    prompt = template.replace("{founder_profile}", json.dumps(founder, indent=2))

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert NVIDIA Inception program analyst. "
                    "Return ONLY valid JSON. No markdown, no preamble, no explanation."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,   # Lower temp for structured output
        max_tokens=1024,
        stream=False
    )

    raw = completion.choices[0].message.content.strip()

    # Strip markdown fences if model added them anyway
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)

    parsed = json.loads(raw)

    # Handle both {"signals": [...]} and [...] formats
    if isinstance(parsed, dict) and "signals" in parsed:
        return parsed["signals"]
    if isinstance(parsed, list):
        return parsed

    raise ValueError(f"Unexpected JSON shape: {type(parsed)}")


# ── Rule-based fallback ───────────────────────────────────────────────────────

def _rule_based_analyze(founder: dict) -> list:
    """
    Apply deterministic rules to produce risk signals without a NIM call.
    Always returns at least one signal.
    """
    signals = []

    for rule in RULE_BASED_SIGNALS:
        try:
            if rule["check"](founder):
                signals.append({
                    "severity":       rule["severity"],
                    "title":          rule["title"],
                    "description":    rule["description"],
                    "manager_action": rule["manager_action"]
                })
        except Exception:
            continue

    # Always include a positive signal if founder has compliance requirements
    if founder.get("compliance_requirements"):
        reqs = ", ".join(founder["compliance_requirements"])
        signals.append({
            "severity": "low",
            "title": f"Compliance Requirements Mapped ({reqs})",
            "description": (
                f"Founder has identified {reqs} as active compliance requirements. "
                "This is a positive signal — they understand the procurement context "
                "their product will need to navigate."
            ),
            "manager_action": "Use this in the first meeting to introduce NIM on-premise as the architecture that makes compliance a feature, not a constraint."
        })

    # If no rules fired, return a generic healthy signal
    if not signals:
        signals.append({
            "severity": "low",
            "title": "No Major Risk Signals Detected",
            "description": (
                f"{founder.get('founder_name', 'This founder')} has a clear domain, "
                "defined stack, and stated 12-month goal. No structural blockers identified from intake."
            ),
            "manager_action": "Probe for unstated risks in the first meeting. Ask: 'What's the thing keeping you up at night that you didn't put in the intake?'"
        })

    return signals
