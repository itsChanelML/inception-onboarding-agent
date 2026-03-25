# Inception Onboarding Agent

An AI-powered onboarding agent for NVIDIA Inception Program founders.
Built with Nemotron via NVIDIA NIM, designed to run inside NemoClaw's OpenShell sandbox.

## What It Does

Takes a founder intake profile and generates two documents:
- **Vision Translation Brief** — maps the founder's vision to the NVIDIA stack
- **12-Month Milestone Roadmap** — milestone path from prototype to production

## Stack

| Layer | Tool |
|---|---|
| Intelligence | Nemotron via NVIDIA NIM |
| Agent Runtime | Python |
| Security Sandbox | NemoClaw / OpenShell (architecture) |
| UI | Inception Intelligence Portal (Flask) |
| Models | nvidia/nemotron-4-340b-instruct |

## Project Structure
```
inception-onboarding-agent/
├── agent.py              # Main agent orchestration
├── requirements.txt      # Dependencies
├── .env.example          # Environment variables template
├── prompts/
│   ├── vision_brief.txt  # Vision Translation Brief prompt
│   └── roadmap.txt       # 12-Month Roadmap prompt
├── founders/
│   ├── claravision.json  # Maya Chen — medical imaging
│   └── novacrop.json     # Ravi Krishnamurthy — precision agriculture
└── outputs/              # Generated briefs and roadmaps
```

## Setup

1. Clone the repo
2. Copy `.env.example` to `.env` and add your NIM API key
3. Install dependencies
4. Run the agent
```bash
git clone https://github.com/itsChanelML/inception-onboarding-agent
cd inception-onboarding-agent
cp .env.example .env
pip install -r requirements.txt
python agent.py claravision
```

## Usage
```bash
# Generate docs for Maya Chen / ClaraVision
python agent.py claravision

# Generate docs for Ravi Krishnamurthy / NovaCrop AI
python agent.py novacrop
```

## Why This Exists

NVIDIA Inception managers onboard 50+ founders per cohort. Every first meeting
starts cold. This agent compresses the cold-start problem — generating a founder
brief and 12-month roadmap from intake data before the first conversation happens.

The manager arrives prepared. The founder feels seen. The relationship starts
three conversations deep instead of zero.

## Architecture Note

This agent is designed to run inside NemoClaw's OpenShell sandbox for
enterprise-grade security. The OpenShell runtime enforces policy-based privacy
guardrails — ensuring founder data never leaves the defined security perimeter.
This matters for healthcare founders (HIPAA) and fintech founders (SOC 2).

## Built By

Chanel Power — ML Engineer, Founder & CEO of Mentor Me Collective
GitHub: itsChanelML