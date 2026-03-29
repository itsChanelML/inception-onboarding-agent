# Inception Intelligence

An AI-powered onboarding and relationship management platform for NVIDIA Inception Program founders. Built with Nemotron via NVIDIA NIM. Deployed on Vercel with a Flask backend.

---

## What It Does

Inception Intelligence gives every NVIDIA Inception founder a personalized AI advisor (Aria) and every DevRel manager a complete intelligence briefing before their first conversation.

**For founders**, it generates:
- Vision Translation Brief — maps their clinical or technical vision to the NVIDIA stack in plain language
- 12-Month Milestone Roadmap — a milestone path from prototype to production, specific to their domain
- CTO Alignment Brief — surfaces gaps between founder vision and what the engineering team is building

**For managers**, it generates:
- New Founder Brief — Aria's full analysis including risk signals, open questions, and recommended first actions
- Kickoff Meeting Playbook — a 60-minute agenda with what to say, what to listen for, and what to do after
- Profile Change Alerts — detects when a founder updates their profile and flags which documents need regeneration

The manager arrives prepared. The founder feels seen. The relationship starts three conversations deep instead of zero.

---

## Stack

| Layer | Tool |
|-------|------|
| Intelligence | Nemotron via NVIDIA NIM |
| Agent Runtime | Python |
| Backend | Flask |
| Deployment | Vercel (serverless) |
| UI | Inception Intelligence Portal (two-portal HTML/CSS/JS) |
| Model | `nvidia/nemotron-super-49b-v1` |

---

## Project Structure

```
inception-onboarding-agent/
├── api/
│   └── index.py              # Vercel serverless entry point
├── app.py                    # Flask backend — 15 API routes
├── agent.py                  # Batch generation script (local)
├── vercel.json               # Vercel deployment config
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── orchestrator.py       # Coordinates all agents
│   ├── risk_agent.py         # Risk signal detection
│   └── ticket_agent.py       # Ticket triage + response drafting
│
├── prompts/
│   ├── vision_brief.txt      # Vision Translation Brief prompt
│   ├── roadmap.txt           # 12-Month Milestone Roadmap prompt
│   ├── risk_analysis.txt     # Risk signal analysis — returns structured JSON
│   └── aria_chat.txt         # Aria conversation system prompt
│
├── founders/
│   ├── claravision.json      # Dr. Maya Chen — medical imaging AI
│   ├── novacrop.json         # Ravi Krishnamurthy — precision agriculture
│   ├── quantum_dx.json       # Sofia Torres — genomic sequencing AI
│   ├── voicepath_ai.json     # James Mbeki — clinical NLP
│   ├── retinal_ai.json       # Amara Patel — ophthalmology screening
│   └── structure_iq.json     # Lena Nakamura — construction AI
│
├── static/
│   ├── manager_portal.html   # Manager portal — brief, agenda, inbox, Aria
│   └── founder_portal.html   # Founder portal — onboarding, roadmap, community
│
└── outputs/                  # Generated briefs and roadmaps
```

---

## API Routes

| Method | Route | What it does |
|--------|-------|--------------|
| GET | `/` | Manager portal |
| GET | `/founder` | Founder portal |
| GET | `/api/founders` | List all founder profiles |
| GET | `/api/founders/<slug>` | Get a single founder profile |
| PUT | `/api/founders/<slug>` | Update a founder profile field |
| GET | `/api/founders/<slug>/assignment` | Intro overlay data for new assignment |
| GET/POST | `/api/founders/<slug>/brief-status` | Get or set brief read status |
| GET | `/api/founders/<slug>/agenda` | Kickoff agenda metadata |
| POST | `/api/founders/<slug>/profile-change` | Log a profile change, return impact |
| GET/POST | `/api/founders/<slug>/milestones` | Get or update milestone state |
| GET | `/api/generate/<slug>/<doc_type>` | Stream Nemotron generation (local) |
| GET | `/api/generate-sync/<slug>/<doc_type>` | Non-streaming generation (Vercel) |
| POST | `/api/aria/chat` | Aria chat with founder context |
| POST | `/api/onboard` | Save completed onboarding profile |
| POST | `/api/onboard/predict-chips` | AI-predicted suggestion chips |
| GET/POST | `/api/community/threads` | Community thread feed |
| GET/POST | `/api/tickets` | Submit and list support tickets |
| GET | `/api/outputs/<slug>` | Get previously generated documents |

---

## Local Setup

```bash
git clone https://github.com/itsChanelML/inception-onboarding-agent
cd inception-onboarding-agent
cp .env.example .env
# Add your NVIDIA NIM API key to .env
pip install -r requirements.txt
python app.py
```

Manager portal → `http://localhost:5000`  
Founder portal → `http://localhost:5000/founder`

To generate documents from the command line:

```bash
python agent.py claravision
python agent.py novacrop
```

---

## Vercel Deployment

1. Push this repo to GitHub
2. Connect the repo to [vercel.com](https://vercel.com)
3. Add `NVIDIA_API_KEY` as an environment variable in Vercel project settings
4. Deploy — all routes are handled by `api/index.py`

The portal uses `/api/generate-sync` on Vercel instead of the SSE streaming route, since serverless functions do not support long-running connections. The word-by-word brief population animation is CSS — it does not require a live stream.

---

## The Demo Path

The portal tells a single, continuous story across both portals:

1. **Founder arrives** → animated welcome overlay → "Welcome to the program, Maya"
2. **Smart onboarding** → Aria asks 13 questions with AI-predicted suggestion chips → right panel builds live profile in real time → documents unlock progressively → completion screen
3. **Founder portal** → dashboard, roadmap, Vision Translation Brief, Aria chat, community, support tickets
4. **Manager portal** → "New Founder" badge → intro overlay → brief population animation (section by section, green checkmarks) → acknowledgment → kickoff agenda transition
5. **Profile change detection** → amber alert bar → regenerate brief modal → brief repopulates with updated content
6. **Ticket inbox** → Aria triage draft pre-loaded → manager sends reply

---

## Founder Profiles

Six founders across five domains, each with distinct NVIDIA stack requirements:

| Founder | Company | Domain | Key NVIDIA Tools |
|---------|---------|--------|-----------------|
| Dr. Maya Chen | ClaraVision | Medical Imaging AI | NIM On-Prem, Clara, MONAI, FLARE |
| Ravi Krishnamurthy | NovaCrop AI | Precision Agriculture | Jetson Orin, TAO Toolkit, NIM |
| Sofia Torres | Quantum Dx | Genomic Sequencing | BioNeMo, DGX Cloud, NIM |
| James Mbeki | VoicePathAI | Clinical NLP | NeMo, Riva, NIM |
| Amara Patel | RetinalAI | Ophthalmology Screening | Clara, MONAI, NIM |
| Lena Nakamura | StructureIQ | Construction AI | Metropolis, Jetson Orin, DeepStream |

---

## Why This Exists

NVIDIA Inception managers onboard 50+ founders per cohort. Every first meeting starts cold. This platform compresses the cold-start problem — generating a complete founder brief, milestone roadmap, and kickoff agenda from intake data before the first conversation happens.

At scale, Aria handles the pattern recognition and document generation. The manager handles the relationship. The founder gets both.

---

## Built By

**Chanel Power** — Senior ML Engineer · Founder & CEO of Mentor Me Collective  
GitHub: [itsChanelML](https://github.com/itsChanelML)
