# Inception Intelligence

An AI-powered onboarding and relationship management platform for NVIDIA Inception Program founders. Built with Nemotron via NVIDIA NIM. Deployed on Vercel with a Flask backend.

**Live:** [inception-onboarding-agent.vercel.app](https://inception-onboarding-agent.vercel.app)

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
- Morning Portfolio Scan — daily AI briefing across all founders with prioritized action list
- Pattern Match Intelligence — surfaces analogous successful founder journeys with lessons

The manager arrives prepared. The founder feels seen. The relationship starts three conversations deep instead of zero.

---

## Stack

| Layer | Tool |
|-------|------|
| Intelligence | Nemotron via NVIDIA NIM (`nvidia/nemotron-super-49b-v1`) |
| Fast inference | `nvidia/nemotron-nano-8b-v1` (chip prediction, triage) |
| Agent Runtime | Python 5,770+ lines across 6 agents, 5 tools, 4 schemas |
| Backend | Flask — 24 API routes |
| Deployment | Vercel (serverless) |
| UI | Two-portal HTML/CSS/JS — Manager + Founder |
| Data validation | Pydantic v2 |
| Tests | pytest — 99 passing |

---

## Project Structure

```
inception-onboarding-agent/
├── api/
│   └── index.py                  # Vercel serverless entry point
├── app.py                        # Flask backend — 24 API routes (877 lines)
├── agent.py                      # Batch generation script (local)
├── vercel.json                   # Vercel deployment config
├── requirements.txt
│
├── agents/
│   ├── orchestrator.py           # Coordinates all agents for a founder
│   ├── risk_agent.py             # Risk signal detection (CTO gap, benefit lag, etc.)
│   ├── ticket_agent.py           # Ticket triage + Aria response drafting
│   ├── onboarding_agent.py       # 13-question intake + NIM chip prediction
│   ├── pattern_matcher.py        # Analogous founder journey matching
│   └── monitor_agent.py          # Morning portfolio health scan
│
├── tools/
│   ├── nim_client.py             # Reusable NIM wrapper (retry, streaming, JSON)
│   ├── founder_db.py             # Read/write/version founder profiles
│   ├── memory.py                 # Per-founder Aria conversation memory
│   ├── vector_store.py           # ChromaDB RAG for community search
│   └── journey_tracker.py        # Milestone velocity, health signals, cohort comparison
│
├── schemas/
│   ├── founder_profile.py        # Pydantic founder schema with validators
│   ├── milestone.py              # Milestone structure + 7 default templates
│   ├── ticket.py                 # Ticket schema + routing rules table
│   └── journey.py                # Success pattern schema + 3 seed patterns
│
├── prompts/
│   ├── vision_brief.txt          # Vision Translation Brief prompt
│   ├── roadmap.txt               # 12-Month Milestone Roadmap prompt
│   ├── risk_analysis.txt         # Risk signal analysis prompt
│   └── aria_chat.txt             # Aria conversation system prompt
│
├── founders/
│   ├── claravision.json          # Dr. Maya Chen — medical imaging AI
│   ├── novacrop.json             # Ravi Krishnamurthy — precision agriculture
│   ├── quantum_dx.json           # Sofia Torres — genomic sequencing AI
│   ├── voicepath_ai.json         # James Mbeki — clinical NLP
│   ├── retinal_ai.json           # Amara Patel — ophthalmology screening
│   └── structure_iq.json         # Lena Nakamura — construction AI
│
├── static/
│   ├── manager_portal.html       # Manager portal — brief, agenda, inbox, Aria
│   └── founder_portal.html       # Founder portal — onboarding, roadmap, community
│
├── tests/
│   ├── conftest.py               # Shared fixtures
│   ├── test_schemas.py           # 44 schema validation tests
│   ├── test_pattern_matcher.py   # 31 scoring + matching tests
│   ├── test_onboarding_agent.py  # 24 question + chip prediction tests
│   └── test_routes.py            # Flask route smoke tests
│
└── outputs/                      # Generated briefs and roadmaps (local only)
```

---

## API Routes

| Method | Route | Agent | What it does |
|--------|-------|-------|--------------|
| GET | `/` | — | Manager portal |
| GET | `/founder` | — | Founder portal |
| GET | `/api/health` | — | Health check — agents loaded, founder count, NIM status |
| GET | `/api/founders` | FounderDB | List all founder profiles |
| GET | `/api/founders/<slug>` | FounderDB | Get a single founder profile |
| PUT | `/api/founders/<slug>` | FounderDB | Update a founder profile field |
| GET | `/api/founders/<slug>/assignment` | JourneyTracker | Intro overlay data |
| GET/POST | `/api/founders/<slug>/brief-status` | — | Get or set brief read status |
| GET | `/api/founders/<slug>/agenda` | — | Kickoff agenda metadata |
| POST | `/api/founders/<slug>/profile-change` | FounderDB | Log a profile change, return impact |
| GET/POST | `/api/founders/<slug>/milestones` | JourneyTracker | Get or update milestone state |
| GET | `/api/founders/<slug>/risks` | RiskAgent | Risk signals for a founder |
| GET | `/api/patterns/<slug>` | PatternMatcher | Analogous founder matches + manager recommendation |
| GET | `/api/morning-scan` | MonitorAgent | Full portfolio health scan with NIM briefing |
| POST | `/api/orchestrate/<slug>` | Orchestrator | Run all agents for a founder |
| GET | `/api/generate/<slug>/<doc_type>` | NIMClient | Stream Nemotron generation (local only) |
| GET | `/api/generate-sync/<slug>/<doc_type>` | NIMClient | Non-streaming generation (Vercel) |
| POST | `/api/aria/chat` | Memory + NIMClient | Aria chat with founder context + memory |
| POST | `/api/onboard` | OnboardingAgent | Save completed onboarding profile |
| POST | `/api/onboard/predict-chips` | OnboardingAgent | AI-predicted suggestion chips (NANO model) |
| GET/POST | `/api/community/threads` | — | Community thread feed |
| POST | `/api/community/search` | VectorStore | RAG search across community + docs |
| GET/POST | `/api/tickets` | TicketAgent | Submit and list support tickets |
| GET | `/api/outputs/<slug>` | FounderDB | Get previously generated documents |

---

## Agent Architecture

### MonitorAgent — Morning Portfolio Scan
Runs daily across all 6 founders. Checks Aria session activity, benefit activation, open tickets, milestone velocity, and runs PatternMatcher on at-risk founders. Uses NIM NANO to generate a plain-English briefing for the manager.

### PatternMatcher — Analogous Journey Matching
Scores each founder against 3 seed success patterns across 6 dimensions: domain, deployment target, compliance, NVIDIA tools, primary challenge, funding stage. Returns top N matches with similarity score, key insight, and recommended manager action.

### OnboardingAgent — Conversational Intake
Owns all 13 onboarding questions across 5 chapters (Vision, Technical, Team, Market, Ask). Uses NIM NANO for real-time chip prediction during onboarding. Synthesizes `primary_challenge` and `investor_narrative` from completed answers.

### RiskAgent — Signal Detection
Detects CTO alignment gaps, benefit activation lag, Aria silence, milestone stalls, and compliance gaps from founder profile data. Returns structured signals with severity and manager action.

### TicketAgent — Triage + Response Drafting
Classifies tickets by category and urgency. Routes to manager, Aria, or Aria-then-manager based on a routing rules table. Drafts responses using NIM with full founder context.

### Orchestrator — Full Agent Run
Coordinates brief generation, roadmap generation, and risk analysis for a single founder. Used for initial onboarding and profile change regeneration.

---

## Ticket Routing Logic

| Category | Urgency | Routing |
|----------|---------|---------|
| Technical | Urgent | Manager |
| Compliance | Urgent | Manager |
| Partnership | Urgent | Manager |
| Technical | Moderate | Aria → Manager review |
| Technical | General | Aria (auto-resolve) |
| General | General | Aria (auto-resolve) |
| Billing | Any | Aria → Manager review |

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
Health check → `http://localhost:5000/api/health`

To generate documents from the command line:

```bash
python agent.py claravision
python agent.py novacrop
```

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

99 tests across schemas, pattern matching, onboarding agent, and route smoke tests. All pass. NIM calls are mocked — no API key required to run tests.

```
tests/test_schemas.py          44 passed
tests/test_pattern_matcher.py  31 passed
tests/test_onboarding_agent.py 24 passed
tests/test_routes.py           (route smoke tests)
```

---

## Vercel Deployment

1. Push this repo to GitHub
2. Connect the repo to [vercel.com](https://vercel.com)
3. Add `NVIDIA_API_KEY` as an environment variable in Vercel project settings
4. Deploy — all routes are handled by `api/index.py`

The platform uses `/api/generate-sync` on Vercel instead of the SSE streaming route, since serverless functions do not support long-running connections. The Vercel filesystem is read-only — all disk writes are skipped automatically via `IS_VERCEL` environment detection.

---

## Live API Verification

```bash
# Health check
curl https://inception-onboarding-agent.vercel.app/api/health

# Morning portfolio scan
curl https://inception-onboarding-agent.vercel.app/api/morning-scan

# Pattern matching for ClaraVision
curl https://inception-onboarding-agent.vercel.app/api/patterns/claravision

# Risk signals for ClaraVision
curl https://inception-onboarding-agent.vercel.app/api/founders/claravision/risks
```

---

## The Demo Path

The platform tells a single continuous story across both portals:

1. **Founder arrives** → animated welcome overlay → "Welcome to the program, Maya"
2. **Smart onboarding** → Aria asks 13 questions with AI-predicted suggestion chips → right panel builds live profile in real time → documents unlock progressively → completion screen
3. **Founder portal** → dashboard, roadmap, Vision Translation Brief, Aria chat (live NIM), community, support tickets (wired to backend)
4. **Manager portal** → "New Founder" badge → intro overlay → brief population animation (section by section, green checkmarks) → acknowledgment → kickoff agenda transition
5. **Morning scan** → Aria's daily briefing with portfolio health, priority actions, and pattern match insights
6. **Profile change detection** → amber alert bar → regenerate brief modal → brief repopulates
7. **Ticket inbox** → Aria triage draft pre-loaded → manager sends reply

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

**Chanel Power** — Senior ML Engineer · DevRel Manager · Founder & CEO of Mentor Me Collective
GitHub: [itsChanelML](https://github.com/itsChanelML) · [@itsChanelML](https://twitter.com/itsChanelML)