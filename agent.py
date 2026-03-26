import json
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-super-120b-a12b"

# ── Load Files ─────────────────────────────────────────────────────────────────

def load_founder(founder_slug: str) -> dict:
    path = Path(f"founders/{founder_slug}.json")
    if not path.exists():
        print(f"[ERROR] Founder file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)

def load_prompt(prompt_name: str, founder_profile: dict) -> str:
    path = Path(f"prompts/{prompt_name}.txt")
    if not path.exists():
        print(f"[ERROR] Prompt file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        template = f.read()
    return template.replace("{founder_profile}", json.dumps(founder_profile, indent=2))

# ── Call NIM ───────────────────────────────────────────────────────────────────

def call_nim(prompt: str, task_name: str) -> str:
    try:
        from openai import OpenAI

        print(f"[Agent] Calling Nemotron via NIM for: {task_name}...")

        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
        )

        completion = client.chat.completions.create(
            model="nvidia/nemotron-3-super-120b-a12b",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert NVIDIA Inception technical advisor helping founders deploy AI at production scale."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=1,
            top_p=0.95,
            max_tokens=16384,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": 16384
            },
            stream=True
        )

        # Collect streamed response
        full_response = ""
        print(f"[Agent] Streaming response", end="", flush=True)
        for chunk in completion:
            if not chunk.choices:
                continue
            if chunk.choices[0].delta.content is not None:
                full_response += chunk.choices[0].delta.content
                print(".", end="", flush=True)
        print(" done.")

        return full_response

    except Exception as e:
        print(f"[ERROR] NIM call failed: {e}")
        sys.exit(1)

# ── Save Output ────────────────────────────────────────────────────────────────

def save_output(content: str, founder_slug: str, doc_type: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"outputs/{founder_slug}_{doc_type}_{timestamp}.md"
    with open(filename, "w") as f:
        f.write(content)
    print(f"[Agent] Saved → {filename}")
    return filename

# ── Main ───────────────────────────────────────────────────────────────────────

def run(founder_slug: str):
    print(f"\n{'='*60}")
    print(f"  NVIDIA Inception Onboarding Agent")
    print(f"  Founder: {founder_slug}")
    print(f"  Model: Nemotron via NIM")
    print(f"{'='*60}\n")

    # Load founder profile
    print(f"[Agent] Loading founder profile: {founder_slug}...")
    founder = load_founder(founder_slug)
    print(f"[Agent] Founder: {founder['founder_name']} — {founder['company']}")
    print(f"[Agent] Domain: {founder['domain']}")
    print(f"[Agent] Primary challenge: {founder['primary_challenge'][:80]}...\n")

    # Generate Vision Translation Brief
    print(f"[Agent] Generating Vision Translation Brief...")
    brief_prompt = load_prompt("vision_brief", founder)
    brief = call_nim(brief_prompt, "Vision Translation Brief")
    brief_file = save_output(brief, founder_slug, "vision_brief")

    # Generate 12-Month Roadmap
    print(f"\n[Agent] Generating 12-Month Roadmap...")
    roadmap_prompt = load_prompt("roadmap", founder)
    roadmap = call_nim(roadmap_prompt, "12-Month Roadmap")
    roadmap_file = save_output(roadmap, founder_slug, "roadmap")

    # Summary
    print(f"\n{'='*60}")
    print(f"  COMPLETE")
    print(f"{'='*60}")
    print(f"  Vision Brief  → {brief_file}")
    print(f"  Roadmap       → {roadmap_file}")
    print(f"\n  Founder {founder['founder_name']} is ready for their first meeting.\n")

# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage: python agent.py <founder_slug>")
        print("Example: python agent.py claravision")
        print("Example: python agent.py novacrop\n")
        sys.exit(1)

    founder_slug = sys.argv[1]
    run(founder_slug)