"""
agents/ticket_agent.py

Triages a founder support ticket and drafts a response using NIM.

Two functions:
  triage(ticket, founder, client)  → category + urgency classification
  draft_response(ticket, founder, client) → a reply the manager can send as-is or edit

Called by: app.py POST /api/tickets
The draft is returned to the manager portal where they can edit before sending.
"""

import os
import json
import re
from pathlib import Path
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL        = "nvidia/nemotron-super-49b-v1"

CATEGORIES   = ["technical", "partnership", "compliance", "billing", "general"]
URGENCY      = ["urgent", "moderate", "general"]

# Keywords that bump urgency to urgent regardless of NIM classification
URGENT_KEYWORDS = [
    "urgent", "blocking", "blocked", "can't deploy", "cannot deploy",
    "production down", "hipaa", "compliance issue", "data breach",
    "investor meeting", "demo tomorrow", "pitch"
]


# ── Public interface ──────────────────────────────────────────────────────────

def triage(ticket_text: str, founder: dict, client: OpenAI = None) -> dict:
    """
    Classify a ticket's category and urgency.

    Returns:
    {
        "category": str,   # one of CATEGORIES
        "urgency":  str,   # one of URGENCY
        "reason":   str    # one sentence explaining the classification
    }
    """
    # Rule: keyword-based urgent override (no NIM needed)
    lower = ticket_text.lower()
    is_urgent = any(kw in lower for kw in URGENT_KEYWORDS)

    if client is not None:
        try:
            result = _nim_triage(ticket_text, founder, client)
            if is_urgent:
                result["urgency"] = "urgent"
            return result
        except Exception as e:
            print(f"[TicketAgent] NIM triage failed, using rules: {e}")

    return _rule_triage(ticket_text, founder, is_urgent)


def draft_response(ticket_text: str, founder: dict, client: OpenAI = None) -> str:
    """
    Draft a response to a founder ticket.

    Returns a string — the draft message.
    Falls back to a generic acknowledgment if NIM call fails.
    """
    if client is not None:
        try:
            return _nim_draft(ticket_text, founder, client)
        except Exception as e:
            print(f"[TicketAgent] NIM draft failed, using fallback: {e}")

    return _fallback_draft(ticket_text, founder)


# ── NIM-powered triage ────────────────────────────────────────────────────────

def _nim_triage(ticket_text: str, founder: dict, client: OpenAI) -> dict:
    prompt = f"""Classify this support ticket.

TICKET:
{ticket_text}

FOUNDER CONTEXT:
- Company: {founder.get('company', 'unknown')}
- Domain: {founder.get('domain', 'unknown')}
- Stack: {', '.join(founder.get('current_stack', []))}
- Compliance: {', '.join(founder.get('compliance_requirements', []))}

Return ONLY this JSON object, no other text:
{{
  "category": "<one of: technical | partnership | compliance | billing | general>",
  "urgency": "<one of: urgent | moderate | general>",
  "reason": "<one sentence>"
}}"""

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a support ticket classifier. Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=200,
        stream=False
    )

    raw = completion.choices[0].message.content.strip()
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)

    result = json.loads(raw)

    # Validate and sanitize
    result["category"] = result.get("category", "general").lower()
    result["urgency"]  = result.get("urgency",  "general").lower()
    result["reason"]   = result.get("reason", "")

    if result["category"] not in CATEGORIES:
        result["category"] = "general"
    if result["urgency"] not in URGENCY:
        result["urgency"] = "general"

    return result


# ── NIM-powered draft ─────────────────────────────────────────────────────────

def _nim_draft(ticket_text: str, founder: dict, client: OpenAI) -> str:
    """
    Call NIM to draft a response. Returns a plain string.
    """
    system = (
        "You are Aria, the AI technical advisor for NVIDIA Inception. "
        "You are drafting a response that the founder's DevRel manager will review and send. "
        "Be specific, technical, and direct. Under 200 words. "
        "Refer to the founder by first name. "
        "End with a concrete next step."
    )

    first_name = (founder.get("founder_name", "").split()[0] or "there")

    prompt = f"""Draft a response to this ticket from {founder.get('founder_name', 'the founder')} at {founder.get('company', 'their company')}.

FOUNDER STACK: {', '.join(founder.get('nvidia_tools', founder.get('current_stack', [])))}
COMPLIANCE: {', '.join(founder.get('compliance_requirements', ['none stated']))}
PRIMARY CHALLENGE: {founder.get('primary_challenge', 'not specified')}

TICKET:
{ticket_text}

Write the response addressed to {first_name}. Do not include a subject line. Plain text only."""

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        temperature=0.75,
        max_tokens=512,
        stream=False
    )

    return completion.choices[0].message.content.strip()


# ── Rule-based fallbacks ──────────────────────────────────────────────────────

def _rule_triage(ticket_text: str, founder: dict, is_urgent: bool) -> dict:
    """Classify without NIM using keyword matching."""
    lower = ticket_text.lower()

    if any(w in lower for w in ["nim", "gpu", "cuda", "model", "deploy", "inference", "training", "error", "stack", "gke", "kubernetes"]):
        category = "technical"
    elif any(w in lower for w in ["hipaa", "compliance", "gdpr", "soc 2", "fedramp", "audit"]):
        category = "compliance"
    elif any(w in lower for w in ["investor", "vc", "intro", "capital connect", "partner", "co-marketing"]):
        category = "partnership"
    elif any(w in lower for w in ["credits", "billing", "invoice", "payment", "cost"]):
        category = "billing"
    else:
        category = "general"

    urgency = "urgent" if is_urgent else "moderate" if category in ["technical", "compliance"] else "general"

    return {
        "category": category,
        "urgency":  urgency,
        "reason":   f"Classified as {category} based on keyword matching."
    }


def _fallback_draft(ticket_text: str, founder: dict) -> str:
    """Generic acknowledgment draft when NIM is unavailable."""
    first_name = founder.get("founder_name", "").split()[0] or "there"
    company    = founder.get("company", "your company")
    return (
        f"Hi {first_name} — thanks for reaching out. "
        f"I've reviewed your question and I'm looking into this for {company}. "
        "I'll follow up with a specific answer shortly. "
        "In the meantime, if this is blocking a deployment, please mark the ticket urgent so I can prioritize."
    )
