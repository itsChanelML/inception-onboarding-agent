import os
import json
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="static")

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("manager_portal.html")

@app.route("/founder")
def founder():
    return render_template("founder_portal.html")

@app.route("/manager")
def manager():
    return render_template("manager_portal.html")

# ── API: List founders ──────────────────────────────────────────────────────────

@app.route("/api/founders")
def list_founders():
    founders_dir = Path("founders")
    founders = []
    for f in founders_dir.glob("*.json"):
        with open(f) as fp:
            data = json.load(fp)
            founders.append({
                "slug": f.stem,
                "name": data.get("founder_name"),
                "company": data.get("company"),
                "domain": data.get("domain"),
                "funding_stage": data.get("funding_stage"),
                "primary_challenge": data.get("primary_challenge", "")[:100]
            })
    return jsonify(founders)

# ── API: Get founder profile ────────────────────────────────────────────────────

@app.route("/api/founders/<slug>")
def get_founder(slug):
    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Founder not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))

# ── API: Generate brief (streaming) ────────────────────────────────────────────

@app.route("/api/generate/<slug>/<doc_type>")
def generate(slug, doc_type):
    """
    Streams the Nemotron response back to the portal in real time.
    doc_type: vision_brief | roadmap
    """

    def stream():
        try:
            from openai import OpenAI

            NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
            if not NVIDIA_API_KEY:
                yield "data: ERROR: NVIDIA_API_KEY not set\n\n"
                return

            # Load founder
            path = Path(f"founders/{slug}.json")
            if not path.exists():
                yield f"data: ERROR: Founder {slug} not found\n\n"
                return

            with open(path) as f:
                founder = json.load(f)

            # Load prompt
            prompt_path = Path(f"prompts/{doc_type}.txt")
            if not prompt_path.exists():
                yield f"data: ERROR: Prompt {doc_type} not found\n\n"
                return

            with open(prompt_path) as f:
                template = f.read()

            prompt = template.replace(
                "{founder_profile}",
                json.dumps(founder, indent=2)
            )

            yield f"data: [GENERATING] {doc_type} for {founder['founder_name']}...\n\n"

            # Call Nemotron via NIM
            client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=NVIDIA_API_KEY
            )

            completion = client.chat.completions.create(
                model="nvidia/nemotron-super-49b-v1",
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
                max_tokens=4096,
                stream=True
            )

            full_response = ""
            for chunk in completion:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    full_response += content
                    # Stream each chunk to the browser
                    safe = content.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"

            # Save output
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"outputs/{slug}_{doc_type}_{timestamp}.md"
            Path("outputs").mkdir(exist_ok=True)
            with open(output_path, "w") as f:
                f.write(full_response)

            yield f"data: [SAVED] {output_path}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

# ── API: Get existing outputs ───────────────────────────────────────────────────

@app.route("/api/outputs/<slug>")
def get_outputs(slug):
    outputs_dir = Path("outputs")
    files = []
    for f in outputs_dir.glob(f"{slug}_*.md"):
        with open(f) as fp:
            content = fp.read()
        files.append({
            "filename": f.name,
            "doc_type": "vision_brief" if "vision_brief" in f.name else "roadmap",
            "content": content,
            "timestamp": f.stem.split("_")[-2] + "_" + f.stem.split("_")[-1]
        })
    files.sort(key=lambda x: x["timestamp"], reverse=True)
    return jsonify(files)

# ── FEATURE 1: New Founder Assignment State ──────────────────────────────────

@app.route("/api/founders/<slug>/assignment")
def founder_assignment(slug):
    """Returns intro overlay data for a specific founder."""
    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        data = json.load(f)
    return jsonify({
        "founder_name": data.get("founder_name"),
        "company": data.get("company"),
        "domain": data.get("domain"),
        "days_since_joined": 14,  # In production: calculate from join_date
        "first_meeting_pending": True,
        "manager_name": "Chanel Power",
        "manager_title": "Inception DevRel Manager · Group 4"
    })


# ── FEATURE 2-3: Brief Population & Acknowledgment ──────────────────────────

@app.route("/api/founders/<slug>/brief-status", methods=["GET", "POST"])
def brief_status(slug):
    """GET: returns brief read status. POST: marks brief as read."""
    status_path = Path(f"outputs/{slug}_brief_status.json")
    
    if request.method == "POST":
        data = {"read": True, "read_at": __import__("datetime").datetime.now().isoformat()}
        with open(status_path, "w") as f:
            json.dump(data, f)
        return jsonify({"success": True, "read_at": data["read_at"]})
    
    if status_path.exists():
        with open(status_path) as f:
            return jsonify(json.load(f))
    return jsonify({"read": False})


# ── FEATURE 4: Kickoff Agenda ────────────────────────────────────────────────

@app.route("/api/founders/<slug>/agenda")
def get_agenda(slug):
    """Returns the kickoff agenda data for a founder."""
    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        data = json.load(f)
    # Agenda is static per spec — returns metadata, HTML renders the content
    return jsonify({
        "founder_name": data.get("founder_name"),
        "company": data.get("company"),
        "duration_minutes": 60,
        "blocks": 6,
        "primary_challenge": data.get("primary_challenge", "")
    })


# ── FEATURE 5: Profile Change Detection ─────────────────────────────────────

@app.route("/api/founders/<slug>/profile-change", methods=["POST"])
def log_profile_change(slug):
    """Logs a profile field change and returns impact assessment."""
    body = request.get_json()
    field = body.get("field")
    old_val = body.get("old_value")
    new_val = body.get("new_value")
    
    change_path = Path(f"outputs/{slug}_profile_changes.json")
    changes = []
    if change_path.exists():
        with open(change_path) as f:
            changes = json.load(f)
    
    changes.append({
        "field": field,
        "old_value": old_val,
        "new_value": new_val,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "affects_documents": ["Vision Translation Brief", "12-Month Roadmap"]
    })
    
    with open(change_path, "w") as f:
        json.dump(changes, f)
    
    return jsonify({
        "change_logged": True,
        "field": field,
        "affects_documents": ["Vision Translation Brief", "12-Month Roadmap"],
        "regenerate_recommended": True
    })


# ── FEATURE 6: Founder Aria Chat ─────────────────────────────────────────────

@app.route("/api/aria/chat", methods=["POST"])
def aria_chat():
    """Aria chat endpoint — returns a response based on founder context."""
    body = request.get_json()
    message = body.get("message", "")
    founder_slug = body.get("founder_slug", "claravision")
    
    # Load founder context
    path = Path(f"founders/{founder_slug}.json")
    if path.exists():
        with open(path) as f:
            founder = json.load(f)
    else:
        founder = {}
    
    try:
        from openai import OpenAI
        NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
        
        system_prompt = f"""You are Aria, the AI technical advisor for NVIDIA Inception.
You already know this founder intimately:
- Name: {founder.get('founder_name', 'the founder')}
- Company: {founder.get('company', '')}
- Domain: {founder.get('domain', '')}
- Current challenge: {founder.get('primary_challenge', '')}
- Stack: {', '.join(founder.get('current_stack', []))}
- NVIDIA tools: {', '.join(founder.get('nvidia_tools', []))}
- Compliance: {', '.join(founder.get('compliance_requirements', []))}

Keep responses concise, specific, and technical. Never explain who you are. Speak as if this is an ongoing relationship."""
        
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
        )
        completion = client.chat.completions.create(
            model="nvidia/nemotron-super-49b-v1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.8,
            max_tokens=1024,
            stream=False
        )
        response = completion.choices[0].message.content
        return jsonify({"response": response, "founder": founder.get("founder_name")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── FEATURE 7: Milestone Tracker ─────────────────────────────────────────────

@app.route("/api/founders/<slug>/milestones", methods=["GET"])
def get_milestones(slug):
    """Returns milestone completion state for a founder."""
    state_path = Path(f"outputs/{slug}_milestones.json")
    if state_path.exists():
        with open(state_path) as f:
            return jsonify(json.load(f))
    # Default state: first 2 complete, 3rd in progress
    return jsonify({
        "milestones": [
            {"id": 1, "status": "complete", "pct": 100},
            {"id": 2, "status": "complete", "pct": 100},
            {"id": 3, "status": "active", "pct": 40},
            {"id": 4, "status": "locked", "pct": 0},
            {"id": 5, "status": "locked", "pct": 0},
            {"id": 6, "status": "locked", "pct": 0},
            {"id": 7, "status": "locked", "pct": 0},
        ]
    })

@app.route("/api/founders/<slug>/milestones/<int:milestone_id>", methods=["POST"])
def update_milestone(slug, milestone_id):
    """Updates a milestone's completion state."""
    body = request.get_json()
    pct = body.get("pct", 0)
    status = body.get("status", "active")
    
    state_path = Path(f"outputs/{slug}_milestones.json")
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
    else:
        state = {"milestones": [{"id": i, "status": "locked", "pct": 0} for i in range(1, 8)]}
    
    for ms in state["milestones"]:
        if ms["id"] == milestone_id:
            ms["pct"] = pct
            ms["status"] = status
            if pct == 100:
                ms["status"] = "complete"
                # Unlock next
                for m2 in state["milestones"]:
                    if m2["id"] == milestone_id + 1:
                        m2["status"] = "active"
    
    with open(state_path, "w") as f:
        json.dump(state, f)
    
    return jsonify({"success": True, "updated": milestone_id})


# ── FEATURE 8: Profile Edit ──────────────────────────────────────────────────

@app.route("/api/founders/<slug>", methods=["PUT"])
def update_founder(slug):
    """Updates a founder profile field."""
    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    
    with open(path) as f:
        data = json.load(f)
    
    updates = request.get_json()
    data.update(updates)
    
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    
    return jsonify({"success": True, "slug": slug, "updated_fields": list(updates.keys())})


# ── FEATURE 9: Community ─────────────────────────────────────────────────────

@app.route("/api/community/threads", methods=["GET"])
def get_threads():
    """Returns community threads."""
    threads_path = Path("data/community_threads.json")
    if threads_path.exists():
        with open(threads_path) as f:
            return jsonify(json.load(f))
    # Return the pre-populated sample threads from the spec
    return jsonify({"threads": [
        {"id": 1, "author": "Ravi Krishnamurthy", "company": "NovaCrop AI", "domain": "Edge AI",
         "content": "Just hit Milestone 4 — first paying customer signed. TAO fine-tuning clicked when I stopped trying perfection on the full dataset and did domain-specific subsets first.",
         "replies": 8, "likes": 14, "timestamp": "2 hours ago"},
        {"id": 2, "author": "Sofia Torres", "company": "Quantum Dx", "domain": "Healthcare AI",
         "content": "Has anyone gotten Parabricks running on a GKE cluster with HIPAA controls? Hitting IAM permission issues on the GPU node pool.",
         "replies": 4, "likes": 6, "timestamp": "5 hours ago"},
        {"id": 3, "author": "Lena Nakamura", "company": "StructureIQ", "domain": "Physical AI",
         "content": "6 months in, Premiere Tier achieved. The milestone that changed everything was getting our first co-marketing asset with NVIDIA. Don't sleep on the go-to-market support.",
         "replies": 22, "likes": 47, "timestamp": "Yesterday"},
    ]})

@app.route("/api/community/threads", methods=["POST"])
def post_thread():
    """Posts a new community thread."""
    body = request.get_json()
    threads_path = Path("data/community_threads.json")
    Path("data").mkdir(exist_ok=True)
    
    threads = {"threads": []}
    if threads_path.exists():
        with open(threads_path) as f:
            threads = json.load(f)
    
    new_thread = {
        "id": len(threads["threads"]) + 1,
        "author": body.get("author", "Maya Chen"),
        "company": body.get("company", "ClaraVision"),
        "content": body.get("content", ""),
        "timestamp": "Just now",
        "replies": 0, "likes": 0
    }
    threads["threads"].insert(0, new_thread)
    
    with open(threads_path, "w") as f:
        json.dump(threads, f, indent=2)
    
    return jsonify({"success": True, "thread": new_thread})


# ── FEATURE 10: Support Tickets ──────────────────────────────────────────────

@app.route("/api/tickets", methods=["GET"])
def list_tickets():
    """Lists all tickets."""
    tickets_path = Path("data/tickets.json")
    if tickets_path.exists():
        with open(tickets_path) as f:
            return jsonify(json.load(f))
    return jsonify({"tickets": []})

@app.route("/api/tickets", methods=["POST"])
def submit_ticket():
    """Submits a new support ticket and gets Aria triage."""
    body = request.get_json()
    question = body.get("question", "")
    founder_slug = body.get("founder_slug", "claravision")
    urgency = body.get("urgency", "general")
    
    Path("data").mkdir(exist_ok=True)
    tickets_path = Path("data/tickets.json")
    tickets = {"tickets": []}
    if tickets_path.exists():
        with open(tickets_path) as f:
            tickets = json.load(f)
    
    ticket_id = len(tickets["tickets"]) + 1
    
    # Try Aria triage
    aria_draft = None
    try:
        from openai import OpenAI
        NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_API_KEY)
        
        path = Path(f"founders/{founder_slug}.json")
        founder = {}
        if path.exists():
            with open(path) as f:
                founder = json.load(f)
        
        triage_prompt = f"""Founder question: {question}
Founder context: {founder.get('company')} building {founder.get('domain')} with stack {founder.get('current_stack')}.

Draft a concise, specific technical response. Be direct. Under 150 words."""
        
        completion = client.chat.completions.create(
            model="nvidia/nemotron-super-49b-v1",
            messages=[
                {"role": "system", "content": "You are Aria, NVIDIA Inception AI advisor. Give specific, technical answers."},
                {"role": "user", "content": triage_prompt}
            ],
            temperature=0.7, max_tokens=512, stream=False
        )
        aria_draft = completion.choices[0].message.content
    except Exception:
        aria_draft = "Aria is reviewing this ticket. Your manager will follow up shortly."
    
    ticket = {
        "id": ticket_id,
        "question": question,
        "urgency": urgency,
        "founder_slug": founder_slug,
        "status": "open",
        "aria_draft": aria_draft,
        "submitted_at": __import__("datetime").datetime.now().isoformat()
    }
    tickets["tickets"].insert(0, ticket)
    
    with open(tickets_path, "w") as f:
        json.dump(tickets, f, indent=2)
    
    return jsonify({"ticket_id": ticket_id, "aria_draft": aria_draft, "status": "open"})


# ── SMART ONBOARDING: Chip Prediction ────────────────────────────────────────

@app.route("/api/onboard/predict-chips", methods=["POST"])
def predict_chips():
    """Generates AI-predicted suggestion chips for the next onboarding question."""
    body = request.get_json()
    partial_profile = body.get("partial_profile", {})
    next_question = body.get("next_question", "")
    
    try:
        from openai import OpenAI
        NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_API_KEY)
        
        prompt = f"""Given this partial founder profile: {json.dumps(partial_profile)}

Generate 3 short, specific, likely answers to this question: "{next_question}"

Each answer must be under 12 words. Return ONLY a JSON array of strings, no other text.
Example: ["Answer one", "Answer two", "Answer three"]"""
        
        completion = client.chat.completions.create(
            model="nvidia/nemotron-super-49b-v1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8, max_tokens=200, stream=False
        )
        
        raw = completion.choices[0].message.content.strip()
        # Clean JSON
        import re
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            chips = json.loads(match.group())
            return jsonify({"chips": chips[:4]})
    except Exception:
        pass
    
    return jsonify({"chips": []})  # Frontend falls back to hardcoded chips


# ── ONBOARDING SUBMISSION ────────────────────────────────────────────────────

@app.route("/api/onboard", methods=["POST"])
def submit_onboarding():
    """Saves completed onboarding profile and triggers document generation."""
    body = request.get_json()
    slug = body.get("slug", "new_founder_" + __import__("datetime").datetime.now().strftime("%Y%m%d"))
    
    Path("founders").mkdir(exist_ok=True)
    founder_path = Path(f"founders/{slug}.json")
    
    with open(founder_path, "w") as f:
        json.dump(body, f, indent=2)
    
    return jsonify({"success": True, "slug": slug, "message": "Profile saved. Documents generating."})

# ---- Non-streaming generate route for Vercel

@app.route("/api/generate-sync/<slug>/<doc_type>")
def generate_sync(slug, doc_type):
    """Non-streaming version for Vercel deployment."""
    try:
        from openai import OpenAI
        NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
        
        path = Path(f"founders/{slug}.json")
        if not path.exists():
            return jsonify({"error": f"Founder {slug} not found"}), 404
        with open(path) as f:
            founder = json.load(f)

        prompt_path = Path(f"prompts/{doc_type}.txt")
        if not prompt_path.exists():
            return jsonify({"error": f"Prompt {doc_type} not found"}), 404
        with open(prompt_path) as f:
            template = f.read()

        prompt = template.replace("{founder_profile}", json.dumps(founder, indent=2))

        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
        )
        completion = client.chat.completions.create(
            model="nvidia/nemotron-super-49b-v1",
            messages=[
                {"role": "system", "content": "You are an expert NVIDIA Inception technical advisor helping founders deploy AI at production scale."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4096,
            stream=False
        )
        content = completion.choices[0].message.content
        
        # Save output
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"outputs/{slug}_{doc_type}_{timestamp}.md"
        Path("outputs").mkdir(exist_ok=True)
        with open(output_path, "w") as f:
            f.write(content)
        
        return jsonify({"content": content, "saved_to": output_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Run ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Inception Intelligence Portal")
    print("  Manager Portal  → http://localhost:5000")
    print("  Founder Portal  → http://localhost:5000/founder")
    print("="*60 + "\n")
    app.run(debug=True, port=5000, threaded=True)