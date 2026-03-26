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
                max_tokens=4096,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": True},
                    "reasoning_budget": 4096
                },
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

# ── Run ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Inception Intelligence Portal")
    print("  Manager Portal  → http://localhost:5000")
    print("  Founder Portal  → http://localhost:5000/founder")
    print("="*60 + "\n")
    app.run(debug=True, port=5000, threaded=True)