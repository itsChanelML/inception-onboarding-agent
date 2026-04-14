import os
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="static")

# ── Agent + tool imports ───────────────────────────────────────────────────────
# Wrapped in try/except so the app starts even if a dependency is missing locally

try:
    from tools.nim_client import NIMClient, SUPER, NANO
    from tools.founder_db import FounderDB
    from tools.memory import Memory
    from tools.journey_tracker import JourneyTracker, load_all_trackers
    from agents.orchestrator import run_all, run_brief_only, run_roadmap_only
    from agents.risk_agent import analyze_risks
    from agents.ticket_agent import triage, draft_response
    from agents.onboarding_agent import OnboardingAgent
    from agents.pattern_matcher import PatternMatcher
    from agents.monitor_agent import MonitorAgent

    _nim = NIMClient()
    _db  = FounderDB()
    _onboarding_agent  = OnboardingAgent(nim_client=_nim)
    _pattern_matcher   = PatternMatcher(nim_client=_nim)
    _monitor_agent     = MonitorAgent(nim_client=_nim, founder_db=_db, pattern_matcher=_pattern_matcher)
    AGENTS_LOADED = True

except Exception as _e:
    print(f"[app.py] WARNING: Could not load agents — {_e}")
    print("[app.py] Falling back to inline NIM calls.")
    AGENTS_LOADED = False
    _nim = None
    _db  = None


# ── Portal routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("manager_portal.html")

@app.route("/founder")
def founder():
    return render_template("founder_portal.html")

@app.route("/manager")
def manager():
    return render_template("manager_portal.html")


# ── API: List founders ─────────────────────────────────────────────────────────

@app.route("/api/founders")
def list_founders():
    if AGENTS_LOADED and _db:
        try:
            return jsonify(_db.get_all_summaries())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback — direct file read
    founders_dir = Path("founders")
    founders = []
    for f in founders_dir.glob("*.json"):
        try:
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
        except Exception:
            continue
    return jsonify(founders)


# ── API: Get founder profile ───────────────────────────────────────────────────

@app.route("/api/founders/<slug>")
def get_founder(slug):
    if AGENTS_LOADED and _db:
        try:
            return jsonify(_db.get(slug))
        except FileNotFoundError:
            return jsonify({"error": "Founder not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Founder not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


# ── API: Update founder profile ────────────────────────────────────────────────

@app.route("/api/founders/<slug>", methods=["PUT"])
def update_founder(slug):
    updates = request.get_json()
    if not updates:
        return jsonify({"error": "No updates provided"}), 400

    if AGENTS_LOADED and _db:
        try:
            updated = _db.update(slug, updates)
            return jsonify({
                "success": True,
                "slug": slug,
                "updated_fields": list(updates.keys()),
                "profile": updated
            })
        except FileNotFoundError:
            return jsonify({"error": "Founder not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback
    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        data = json.load(f)
    data.update(updates)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return jsonify({"success": True, "slug": slug, "updated_fields": list(updates.keys())})


# ── API: Founder assignment (intro overlay) ────────────────────────────────────

@app.route("/api/founders/<slug>/assignment")
def founder_assignment(slug):
    if AGENTS_LOADED and _db:
        try:
            data    = _db.get(slug)
            tracker = JourneyTracker(slug)
            return jsonify({
                "founder_name":       data.get("founder_name"),
                "company":            data.get("company"),
                "domain":             data.get("domain"),
                "days_since_joined":  tracker.days_active() or 14,
                "first_meeting_pending": tracker.total_aria_sessions() == 0,
                "manager_name":       "Chanel Power",
                "manager_title":      "Inception DevRel Manager · Group 4"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    path = Path(f"founders/{slug}.json")
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        data = json.load(f)
    return jsonify({
        "founder_name":       data.get("founder_name"),
        "company":            data.get("company"),
        "domain":             data.get("domain"),
        "days_since_joined":  14,
        "first_meeting_pending": True,
        "manager_name":       "Chanel Power",
        "manager_title":      "Inception DevRel Manager · Group 4"
    })


# ── API: Brief status ──────────────────────────────────────────────────────────

@app.route("/api/founders/<slug>/brief-status", methods=["GET", "POST"])
def brief_status(slug):
    status_path = Path(f"outputs/{slug}_brief_status.json")
    Path("outputs").mkdir(exist_ok=True)

    if request.method == "POST":
        data = {"read": True, "read_at": datetime.now().isoformat()}
        with open(status_path, "w") as f:
            json.dump(data, f)
        return jsonify({"success": True, "read_at": data["read_at"]})

    if status_path.exists():
        with open(status_path) as f:
            return jsonify(json.load(f))
    return jsonify({"read": False})


# ── API: Kickoff agenda ────────────────────────────────────────────────────────

@app.route("/api/founders/<slug>/agenda")
def get_agenda(slug):
    if AGENTS_LOADED and _db:
        try:
            data = _db.get(slug)
        except Exception:
            return jsonify({"error": "Not found"}), 404
    else:
        path = Path(f"founders/{slug}.json")
        if not path.exists():
            return jsonify({"error": "Not found"}), 404
        with open(path) as f:
            data = json.load(f)

    return jsonify({
        "founder_name":     data.get("founder_name"),
        "company":          data.get("company"),
        "duration_minutes": 60,
        "blocks":           6,
        "primary_challenge": data.get("primary_challenge", "")
    })


# ── API: Profile change detection ──────────────────────────────────────────────

@app.route("/api/founders/<slug>/profile-change", methods=["POST"])
def log_profile_change(slug):
    body    = request.get_json()
    field   = body.get("field")
    old_val = body.get("old_value")
    new_val = body.get("new_value")

    if AGENTS_LOADED and _db:
        try:
            _db.update(slug, {field: new_val})
            changes = _db.get_changes(slug)
            return jsonify({
                "change_logged":         True,
                "field":                 field,
                "affects_documents":     ["Vision Translation Brief", "12-Month Roadmap"],
                "regenerate_recommended": True,
                "total_changes":         len(changes)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback
    change_path = Path(f"outputs/{slug}_profile_changes.json")
    Path("outputs").mkdir(exist_ok=True)
    changes = []
    if change_path.exists():
        with open(change_path) as f:
            changes = json.load(f)
    changes.append({
        "field": field, "old_value": old_val, "new_value": new_val,
        "timestamp": datetime.now().isoformat(),
        "affects_documents": ["Vision Translation Brief", "12-Month Roadmap"]
    })
    with open(change_path, "w") as f:
        json.dump(changes, f)
    return jsonify({
        "change_logged": True, "field": field,
        "affects_documents": ["Vision Translation Brief", "12-Month Roadmap"],
        "regenerate_recommended": True
    })


# ── API: Aria chat (with memory) ───────────────────────────────────────────────

@app.route("/api/aria/chat", methods=["POST"])
def aria_chat():
    body         = request.get_json()
    message      = body.get("message", "")
    founder_slug = body.get("founder_slug", "claravision")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    # Load founder context
    if AGENTS_LOADED and _db:
        try:
            founder = _db.get(founder_slug)
        except Exception:
            founder = {}
    else:
        path = Path(f"founders/{founder_slug}.json")
        founder = json.load(open(path)) if path.exists() else {}

    # Load or create memory for this founder
    if AGENTS_LOADED:
        memory = Memory.load(founder_slug)
        memory.add_user(message)

        system_prompt = (
            f"You are Aria, the AI technical advisor for NVIDIA Inception. "
            f"You already know this founder:\n"
            f"- Name: {founder.get('founder_name', 'the founder')}\n"
            f"- Company: {founder.get('company', '')}\n"
            f"- Domain: {founder.get('domain', '')}\n"
            f"- Challenge: {founder.get('primary_challenge', '')}\n"
            f"- Stack: {', '.join(founder.get('current_stack', []))}\n"
            f"- NVIDIA tools: {', '.join(founder.get('nvidia_tools', []))}\n"
            f"- Compliance: {', '.join(founder.get('compliance_requirements', []))}\n\n"
            f"Keep responses concise, specific, and technical. "
            f"Never explain who you are. Speak as if this is an ongoing relationship."
        )

        try:
            messages = memory.as_messages(system=system_prompt, last_n=10)
            response = _nim.complete(
                prompt=message,
                system=system_prompt,
                model=SUPER,
                max_tokens=1024,
                temperature=0.8,
            )
            memory.add_aria(response)
            memory.save()
            return jsonify({
                "response":      response,
                "founder":       founder.get("founder_name"),
                "session_turns": memory.turn_count()
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback — inline NIM call
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=os.getenv("NVIDIA_API_KEY")
        )
        system_prompt = (
            f"You are Aria, the AI technical advisor for NVIDIA Inception. "
            f"Founder: {founder.get('founder_name', '')} at {founder.get('company', '')}. "
            f"Domain: {founder.get('domain', '')}. "
            f"Challenge: {founder.get('primary_challenge', '')}. "
            f"Be concise, specific, technical."
        )
        completion = client.chat.completions.create(
            model="nvidia/nemotron-super-49b-v1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.8, max_tokens=1024, stream=False
        )
        return jsonify({
            "response": completion.choices[0].message.content,
            "founder":  founder.get("founder_name")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Milestones ────────────────────────────────────────────────────────────

@app.route("/api/founders/<slug>/milestones", methods=["GET"])
def get_milestones(slug):
    if AGENTS_LOADED:
        try:
            tracker = JourneyTracker(slug)
            return jsonify(tracker.to_dict())
        except Exception:
            pass

    state_path = Path(f"outputs/{slug}_milestones.json")
    if state_path.exists():
        with open(state_path) as f:
            return jsonify(json.load(f))
    return jsonify({
        "milestones": [
            {"id": 1, "status": "complete", "pct": 100},
            {"id": 2, "status": "complete", "pct": 100},
            {"id": 3, "status": "active",   "pct": 40},
            {"id": 4, "status": "locked",   "pct": 0},
            {"id": 5, "status": "locked",   "pct": 0},
            {"id": 6, "status": "locked",   "pct": 0},
            {"id": 7, "status": "locked",   "pct": 0},
        ]
    })


@app.route("/api/founders/<slug>/milestones/<int:milestone_id>", methods=["POST"])
def update_milestone(slug, milestone_id):
    body   = request.get_json()
    pct    = body.get("pct", 0)
    status = body.get("status", "active")
    note   = body.get("note")

    if AGENTS_LOADED:
        try:
            tracker = JourneyTracker(slug)
            if pct == 100 or status == "complete":
                tracker.complete_milestone(milestone_id, note=note)
            else:
                tracker.update_milestone(milestone_id, pct=pct, note=note)
            return jsonify({"success": True, "updated": milestone_id})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback
    state_path = Path(f"outputs/{slug}_milestones.json")
    Path("outputs").mkdir(exist_ok=True)
    state = {"milestones": [{"id": i, "status": "locked", "pct": 0} for i in range(1, 8)]}
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
    for ms in state["milestones"]:
        if ms["id"] == milestone_id:
            ms["pct"]    = pct
            ms["status"] = "complete" if pct == 100 else status
            for m2 in state["milestones"]:
                if pct == 100 and m2["id"] == milestone_id + 1:
                    m2["status"] = "active"
    with open(state_path, "w") as f:
        json.dump(state, f)
    return jsonify({"success": True, "updated": milestone_id})


# ── API: Risk signals ──────────────────────────────────────────────────────────

@app.route("/api/founders/<slug>/risks")
def get_risks(slug):
    if AGENTS_LOADED and _db:
        try:
            founder  = _db.get(slug)
            signals  = analyze_risks(founder, client=_nim._client if _nim else None)
            return jsonify({"signals": signals, "count": len(signals)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"signals": [], "count": 0})


# ── API: Pattern matching ──────────────────────────────────────────────────────

@app.route("/api/patterns/<slug>")
def get_patterns(slug):
    if AGENTS_LOADED and _db:
        try:
            founder = _db.get(slug)
            matches = _pattern_matcher.find_matches(founder, top_n=3)
            recommendation = _pattern_matcher.manager_recommendation(founder, matches)
            return jsonify({
                "slug":           slug,
                "matches": [
                    {
                        "pattern_id":      m.pattern.pattern_id,
                        "domain":          m.pattern.domain,
                        "similarity_pct":  m.similarity_pct,
                        "match_label":     m.match_label,
                        "matched_on":      [d.value for d in m.matched_on],
                        "key_insight":     m.key_insight,
                        "recommended_action": m.recommended_action,
                        "key_unlock":      m.pattern.key_unlock,
                        "outcome":         m.pattern.outcome_description,
                        "lessons":         m.pattern.lessons,
                    }
                    for m in matches
                ],
                "recommendation": recommendation,
                "match_count":    len(matches),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"matches": [], "recommendation": "", "match_count": 0})


# ── API: Morning scan ──────────────────────────────────────────────────────────

@app.route("/api/morning-scan")
def morning_scan():
    if AGENTS_LOADED:
        try:
            report = _monitor_agent.run(manager_name="Chanel")
            return jsonify(report)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({
        "summary": "Agent layer not loaded — run locally with full dependencies.",
        "priority_actions": [],
        "at_risk": [],
        "watch": [],
        "on_track": [],
        "portfolio_stats": {}
    })


# ── API: Full orchestration ────────────────────────────────────────────────────

@app.route("/api/orchestrate/<slug>", methods=["POST"])
def orchestrate(slug):
    """Run all agents for a founder — generates brief, roadmap, risk signals."""
    if AGENTS_LOADED:
        try:
            result = run_all(slug, verbose=False)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Agent layer not available"}), 503


# ── API: Generate brief (streaming, local only) ────────────────────────────────

@app.route("/api/generate/<slug>/<doc_type>")
def generate(slug, doc_type):
    """Streams Nemotron response. Local development only — use generate-sync on Vercel."""
    def stream():
        try:
            if AGENTS_LOADED and _db:
                founder = _db.get(slug)
            else:
                path = Path(f"founders/{slug}.json")
                if not path.exists():
                    yield f"data: ERROR: Founder {slug} not found\n\n"
                    return
                with open(path) as f:
                    founder = json.load(f)

            prompt_path = Path(f"prompts/{doc_type}.txt")
            if not prompt_path.exists():
                yield f"data: ERROR: Prompt {doc_type} not found\n\n"
                return
            with open(prompt_path) as f:
                template = f.read()
            prompt = template.replace("{founder_profile}", json.dumps(founder, indent=2))

            yield f"data: [GENERATING] {doc_type} for {founder.get('founder_name', slug)}...\n\n"

            if AGENTS_LOADED and _nim:
                full_response = ""
                for chunk in _nim.stream(prompt, system="You are an expert NVIDIA Inception technical advisor."):
                    full_response += chunk
                    safe = chunk.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
            else:
                from openai import OpenAI
                client = OpenAI(
                    base_url="https://integrate.api.nvidia.com/v1",
                    api_key=os.getenv("NVIDIA_API_KEY")
                )
                completion = client.chat.completions.create(
                    model="nvidia/nemotron-super-49b-v1",
                    messages=[
                        {"role": "system", "content": "You are an expert NVIDIA Inception technical advisor."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7, top_p=0.95, max_tokens=4096, stream=True
                )
                full_response = ""
                for chunk in completion:
                    if not chunk.choices:
                        continue
                    content = chunk.choices[0].delta.content
                    if content:
                        full_response += content
                        yield f"data: {content.replace(chr(10), '\\n')}\n\n"

            timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path  = f"outputs/{slug}_{doc_type}_{timestamp}.md"
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ── API: Generate sync (Vercel) ────────────────────────────────────────────────

@app.route("/api/generate-sync/<slug>/<doc_type>")
def generate_sync(slug, doc_type):
    """Non-streaming generation for Vercel deployment."""
    try:
        if AGENTS_LOADED:
            if doc_type == "vision_brief":
                result = run_brief_only(slug)
            elif doc_type == "roadmap":
                result = run_roadmap_only(slug)
            else:
                return jsonify({"error": f"Unknown doc_type: {doc_type}"}), 400
            return jsonify(result)

        # Fallback — inline
        from openai import OpenAI
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
            api_key=os.getenv("NVIDIA_API_KEY")
        )
        completion = client.chat.completions.create(
            model="nvidia/nemotron-super-49b-v1",
            messages=[
                {"role": "system", "content": "You are an expert NVIDIA Inception technical advisor."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7, max_tokens=4096, stream=False
        )
        content     = completion.choices[0].message.content
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"outputs/{slug}_{doc_type}_{timestamp}.md"
        Path("outputs").mkdir(exist_ok=True)
        with open(output_path, "w") as f:
            f.write(content)
        return jsonify({"content": content, "saved_to": output_path})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Get outputs ───────────────────────────────────────────────────────────

@app.route("/api/outputs/<slug>")
def get_outputs(slug):
    if AGENTS_LOADED and _db:
        try:
            files = _db.get_outputs(slug)
            return jsonify(files)
        except Exception:
            pass

    outputs_dir = Path("outputs")
    files = []
    for f in outputs_dir.glob(f"{slug}_*.md"):
        try:
            with open(f) as fp:
                content = fp.read()
            files.append({
                "filename": f.name,
                "doc_type": "vision_brief" if "vision_brief" in f.name else "roadmap",
                "content":  content,
                "timestamp": f.stem.split("_")[-2] + "_" + f.stem.split("_")[-1]
            })
        except Exception:
            continue
    files.sort(key=lambda x: x["timestamp"], reverse=True)
    return jsonify(files)


# ── API: Support tickets ───────────────────────────────────────────────────────

@app.route("/api/tickets", methods=["GET"])
def list_tickets():
    tickets_path = Path("data/tickets.json")
    if tickets_path.exists():
        with open(tickets_path) as f:
            return jsonify(json.load(f))
    return jsonify({"tickets": []})


@app.route("/api/tickets", methods=["POST"])
def submit_ticket():
    body         = request.get_json()
    question     = body.get("question", "")
    founder_slug = body.get("founder_slug", "claravision")
    urgency      = body.get("urgency", "general")

    if not question:
        return jsonify({"error": "No question provided"}), 400

    Path("data").mkdir(exist_ok=True)
    tickets_path = Path("data/tickets.json")
    tickets      = {"tickets": []}
    if tickets_path.exists():
        with open(tickets_path) as f:
            tickets = json.load(f)

    ticket_id = len(tickets["tickets"]) + 1

    # Load founder for context
    if AGENTS_LOADED and _db:
        try:
            founder = _db.get(founder_slug)
        except Exception:
            founder = {}
    else:
        path    = Path(f"founders/{founder_slug}.json")
        founder = json.load(open(path)) if path.exists() else {}

    # Triage + draft via ticket_agent
    aria_draft      = None
    triage_result   = {}

    if AGENTS_LOADED and _nim:
        try:
            triage_result = triage(question, founder, _nim._client)
            aria_draft    = draft_response(question, founder, _nim._client)
        except Exception as e:
            print(f"[app.py] ticket_agent failed: {e}")
            aria_draft = "Aria is reviewing this ticket. Your manager will follow up shortly."
    else:
        aria_draft = "Aria is reviewing this ticket. Your manager will follow up shortly."

    ticket = {
        "id":           ticket_id,
        "question":     question,
        "urgency":      triage_result.get("urgency", urgency),
        "category":     triage_result.get("category", "general"),
        "founder_slug": founder_slug,
        "status":       "open",
        "aria_draft":   aria_draft,
        "submitted_at": datetime.now().isoformat()
    }
    tickets["tickets"].insert(0, ticket)
    with open(tickets_path, "w") as f:
        json.dump(tickets, f, indent=2)

    return jsonify({
        "ticket_id":  ticket_id,
        "aria_draft": aria_draft,
        "category":   ticket["category"],
        "urgency":    ticket["urgency"],
        "status":     "open"
    })


# ── API: Community threads ─────────────────────────────────────────────────────

@app.route("/api/community/threads", methods=["GET"])
def get_threads():
    threads_path = Path("data/community_threads.json")
    if threads_path.exists():
        with open(threads_path) as f:
            return jsonify(json.load(f))
    return jsonify({"threads": [
        {
            "id": 1, "author": "Ravi Krishnamurthy", "company": "NovaCrop AI",
            "domain": "Edge AI",
            "content": "Just hit Milestone 4 — first paying customer signed. TAO fine-tuning clicked when I stopped trying perfection on the full dataset and did domain-specific subsets first.",
            "replies": 8, "likes": 14, "timestamp": "2 hours ago"
        },
        {
            "id": 2, "author": "Sofia Torres", "company": "Quantum Dx",
            "domain": "Healthcare AI",
            "content": "Has anyone gotten Parabricks running on a GKE cluster with HIPAA controls? Hitting IAM permission issues on the GPU node pool.",
            "replies": 4, "likes": 6, "timestamp": "5 hours ago"
        },
        {
            "id": 3, "author": "Lena Nakamura", "company": "StructureIQ",
            "domain": "Physical AI",
            "content": "6 months in, Premiere Tier achieved. The milestone that changed everything was getting our first co-marketing asset with NVIDIA. Don't sleep on the go-to-market support.",
            "replies": 22, "likes": 47, "timestamp": "Yesterday"
        },
    ]})


@app.route("/api/community/threads", methods=["POST"])
def post_thread():
    body         = request.get_json()
    threads_path = Path("data/community_threads.json")
    Path("data").mkdir(exist_ok=True)

    threads = {"threads": []}
    if threads_path.exists():
        with open(threads_path) as f:
            threads = json.load(f)

    new_thread = {
        "id":        len(threads["threads"]) + 1,
        "author":    body.get("author", "Maya Chen"),
        "company":   body.get("company", "ClaraVision"),
        "content":   body.get("content", ""),
        "timestamp": "Just now",
        "replies":   0,
        "likes":     0
    }
    threads["threads"].insert(0, new_thread)
    with open(threads_path, "w") as f:
        json.dump(threads, f, indent=2)
    return jsonify({"success": True, "thread": new_thread})


# ── API: Community search (RAG) ────────────────────────────────────────────────

@app.route("/api/community/search", methods=["POST"])
def community_search():
    body  = request.get_json()
    query = body.get("query", "")
    if not query:
        return jsonify({"results": []}), 400

    if AGENTS_LOADED:
        try:
            from tools.vector_store import vs
            if vs:
                results = vs.search(query, n=5)
                return jsonify({"results": results, "query": query})
        except Exception as e:
            print(f"[app.py] Vector search failed: {e}")

    return jsonify({"results": [], "query": query})


# ── API: Onboarding ────────────────────────────────────────────────────────────

@app.route("/api/onboard/predict-chips", methods=["POST"])
def predict_chips():
    body            = request.get_json()
    partial_profile = body.get("partial_profile", {})
    next_question   = body.get("next_question", "")

    if AGENTS_LOADED and _onboarding_agent:
        try:
            chips = _onboarding_agent.predict_chips(partial_profile, next_question)
            return jsonify({"chips": chips})
        except Exception as e:
            print(f"[app.py] Chip prediction failed: {e}")

    return jsonify({"chips": []})


@app.route("/api/onboard", methods=["POST"])
def submit_onboarding():
    body    = request.get_json()
    slug    = body.get("slug", "new_founder_" + datetime.now().strftime("%Y%m%d%H%M%S"))
    answers = {k: v for k, v in body.items() if k != "slug"}

    if AGENTS_LOADED and _onboarding_agent:
        try:
            saved = _onboarding_agent.process_intake(
                slug=slug,
                answers=answers,
                founder_name=body.get("founder_name"),
                company=body.get("company"),
            )
            return jsonify({"success": True, "slug": slug, "profile": saved})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback
    Path("founders").mkdir(exist_ok=True)
    with open(f"founders/{slug}.json", "w") as f:
        json.dump(body, f, indent=2)
    return jsonify({"success": True, "slug": slug, "message": "Profile saved."})


# ── API: Health check ──────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({
        "status":        "ok",
        "agents_loaded": AGENTS_LOADED,
        "nim_available": _nim is not None,
        "founders":      len(_db.list_slugs()) if _db else 0,
        "timestamp":     datetime.now().isoformat(),
    })


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Inception Intelligence")
    print(f"  Agents loaded: {AGENTS_LOADED}")
    print("  Manager Portal → http://localhost:5000")
    print("  Founder Portal → http://localhost:5000/founder")
    print("  Health check   → http://localhost:5000/api/health")
    print("=" * 60 + "\n")
    app.run(debug=True, port=5000, threaded=True)