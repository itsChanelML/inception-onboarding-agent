"""
agents/orchestrator.py

Coordinates all agents for a single founder in sequence:
  1. Load founder profile
  2. Run risk_agent   → risk signals
  3. Generate vision brief via NIM
  4. Generate roadmap via NIM
  5. Save all outputs

Called by: app.py POST /api/orchestrate/<slug>
Called by: agent.py (CLI batch mode)

Usage from app.py:
    from agents.orchestrator import run_all
    result = run_all("claravision")
"""

import os
import json
from pathlib import Path
from datetime import datetime
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL        = "nvidia/nemotron-super-49b-v1"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise EnvironmentError("NVIDIA_API_KEY not set in environment.")
    return OpenAI(base_url=NIM_BASE_URL, api_key=api_key)


def _load_founder(slug: str) -> dict:
    path = Path(f"founders/{slug}.json")
    if not path.exists():
        raise FileNotFoundError(f"Founder profile not found: founders/{slug}.json")
    with open(path) as f:
        return json.load(f)


def _load_prompt(name: str, founder: dict) -> str:
    path = Path(f"prompts/{name}.txt")
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: prompts/{name}.txt")
    with open(path) as f:
        template = f.read()
    return template.replace("{founder_profile}", json.dumps(founder, indent=2))


def _call_nim(client: OpenAI, prompt: str, system: str = None, max_tokens: int = 4096) -> str:
    """Single NIM call. Returns the full response string."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    completion = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
        top_p=0.95,
        max_tokens=max_tokens,
        stream=False
    )
    return completion.choices[0].message.content


def _save_output(content: str, slug: str, doc_type: str) -> str:
    Path("outputs").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"outputs/{slug}_{doc_type}_{timestamp}.md"
    with open(output_path, "w") as f:
        f.write(content)
    return output_path


# ── Core orchestration ────────────────────────────────────────────────────────

def run_all(slug: str, verbose: bool = False) -> dict:
    """
    Run the full agent pipeline for a founder.

    Returns a dict:
    {
        "slug": str,
        "founder_name": str,
        "vision_brief": str,
        "roadmap": str,
        "risk_signals": list,
        "outputs": {
            "vision_brief_path": str,
            "roadmap_path": str,
        },
        "errors": list
    }
    """
    result = {
        "slug": slug,
        "founder_name": None,
        "vision_brief": None,
        "roadmap": None,
        "risk_signals": [],
        "outputs": {},
        "errors": []
    }

    # 1. Load founder
    try:
        founder = _load_founder(slug)
        result["founder_name"] = founder.get("founder_name", slug)
        if verbose:
            print(f"[Orchestrator] Loaded founder: {result['founder_name']}")
    except FileNotFoundError as e:
        result["errors"].append(str(e))
        return result

    client = _get_client()
    system = "You are an expert NVIDIA Inception technical advisor helping founders deploy AI at production scale."

    # 2. Risk signals
    try:
        from agents.risk_agent import analyze_risks
        result["risk_signals"] = analyze_risks(founder, client)
        if verbose:
            print(f"[Orchestrator] Risk signals: {len(result['risk_signals'])} found")
    except Exception as e:
        result["errors"].append(f"risk_agent failed: {e}")
        if verbose:
            print(f"[Orchestrator] WARNING: risk_agent failed — {e}")

    # 3. Vision Translation Brief
    try:
        prompt = _load_prompt("vision_brief", founder)
        brief = _call_nim(client, prompt, system=system, max_tokens=4096)
        result["vision_brief"] = brief
        path = _save_output(brief, slug, "vision_brief")
        result["outputs"]["vision_brief_path"] = path
        if verbose:
            print(f"[Orchestrator] Vision brief saved → {path}")
    except Exception as e:
        result["errors"].append(f"vision_brief failed: {e}")

    # 4. 12-Month Roadmap
    try:
        prompt = _load_prompt("roadmap", founder)
        roadmap = _call_nim(client, prompt, system=system, max_tokens=4096)
        result["roadmap"] = roadmap
        path = _save_output(roadmap, slug, "roadmap")
        result["outputs"]["roadmap_path"] = path
        if verbose:
            print(f"[Orchestrator] Roadmap saved → {path}")
    except Exception as e:
        result["errors"].append(f"roadmap failed: {e}")

    return result


def run_brief_only(slug: str) -> dict:
    """
    Lightweight version — generates only the Vision Translation Brief.
    Used by app.py /api/generate-sync route.
    """
    founder = _load_founder(slug)
    client  = _get_client()
    system  = "You are an expert NVIDIA Inception technical advisor."
    prompt  = _load_prompt("vision_brief", founder)
    content = _call_nim(client, prompt, system=system, max_tokens=4096)
    path    = _save_output(content, slug, "vision_brief")
    return {"content": content, "saved_to": path, "founder": founder.get("founder_name")}


def run_roadmap_only(slug: str) -> dict:
    """
    Generates only the 12-Month Roadmap.
    """
    founder = _load_founder(slug)
    client  = _get_client()
    system  = "You are an expert NVIDIA Inception technical advisor."
    prompt  = _load_prompt("roadmap", founder)
    content = _call_nim(client, prompt, system=system, max_tokens=4096)
    path    = _save_output(content, slug, "roadmap")
    return {"content": content, "saved_to": path, "founder": founder.get("founder_name")}
