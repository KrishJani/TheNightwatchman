# The Nightwatchman

> **A trusted voice beside every call.**

The Nightwatchman is a real-time, multi-agent defense system that listens to live phone
calls and protects vulnerable people — parents, grandparents, anyone — from the scam
tactics designed to manipulate them. As a conversation unfolds, a coordinated team of AI
agents detects coercion patterns, fact-checks suspicious claims, whispers calm coaching
prompts, alerts a trusted family member when help is needed, and generates a formal
incident report after the call.

Everything runs on a single low-latency nervous system: **Redis**. Streams move the
transcript, Pub/Sub fans out live insights, a Bloom filter screens known scammers in
microseconds, Vector Sets match utterances to scam playbooks semantically, and TimeSeries
tracks how risk escalates over the life of the call.

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [What it does](#what-it-does)
- [System design](#system-design)
- [The agent team](#the-agent-team)
- [Redis as the nervous system](#redis-as-the-nervous-system)
- [Latency](#latency)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Running a call](#running-a-call)
- [API reference](#api-reference)
- [Evaluation](#evaluation)
- [Privacy posture](#privacy-posture)

---

## Why this exists

Phone scams are not a technology problem — they are a manipulation problem. Scammers
weaponize urgency, authority, fear, and secrecy faster than a frightened person can think.
Spam blockers stop a number from ringing, but they do nothing once a real conversation is
underway and a real human is being talked into buying gift cards "for the bail clerk."

The Nightwatchman sits *inside* the conversation. It does not just block — it understands,
verifies, coaches, and escalates, in real time, while the call is still happening.

## What it does

- **Real-time scam tactic detection** — classifies each caller utterance into manipulation
  tactics (urgency, authority impersonation, fear, secrecy, gift-card / wire requests).
- **Semantic playbook matching** — recognizes the *shape* of a scam (grandparent scam, IRS
  tax scam, tech-support scam, and more) by vector similarity, not brittle keywords.
- **Known-scammer screening** — checks the inbound number against a probabilistic blocklist
  in microseconds.
- **Live claim verification** — fact-checks suspicious authority and fear claims ("This is
  Officer Harris, badge 4471") and flags what cannot be trusted.
- **Calm coaching** — generates short, reassuring things the person can actually say to buy
  time or end the call safely.
- **Trusted-contact alerts** — when sustained risk crosses a threshold, drafts a calm SMS to
  a family member suggesting they check in.
- **Incident reporting** — produces a clean, formal PDF report of the call for review or
  evidence.
- **Live monitoring console** — a premium React UI that streams the transcript, risk gauge,
  verification tags, coaching tips, and ally alerts as they happen.

## System design

The Nightwatchman is an event-driven pipeline. A call's audio is transcribed and appended to
a Redis Stream; a fleet of independent agent workers consume that stream concurrently and
publish their findings back over Pub/Sub, which the frontend renders live over a WebSocket.

<p align="center">
  <img src="frontend/public/static/diagram-export-6-7-2026-12_38_23-PM.svg" alt="The Nightwatchman system architecture" width="900" />
</p>

At a glance:

1. **Ingestion** turns speech into transcript events — from a live Twilio call, an uploaded
   audio clip (Whisper), or a built-in simulated scam script for demos.
2. **Redis Streams** durably buffer the transcript and fan it out to a consumer group so
   every agent sees every message without stealing work from the others.
3. **Agents** (Sentinel, Verifier, Coach, Ally, Scribe) analyze in parallel and write their
   results back into Redis.
4. **Pub/Sub + WebSocket** push transcript lines, risk alerts, verifications, coaching tips,
   and ally alerts to the live console the moment they are produced.
5. **Weave** traces every LLM call for observability and offline evaluation.

## The agent team

The system reads as a coordinated protection layer rather than a single model. Each agent is
an independent async worker with one job.

| Agent | Role | Model | How it works |
| --- | --- | --- | --- |
| **Sentinel** | Watches the call for scam tactics and risk escalation | `Llama-3.1-8B-Instruct` | Reads the transcript stream via a consumer group, classifies each caller utterance, and matches it against scam playbooks using Vector Sets. Falls back to a deterministic classifier if the LLM is unavailable. |
| **Verifier** | Fact-checks suspicious claims | `Llama-3.3-70B-Instruct` | Subscribes to risk alerts; when an authority/fear claim contains something checkable (a badge number, an agency, an account reference), it assesses credibility and marks red flags. |
| **Coach** | Suggests calm, safe responses | `Llama-3.1-8B-Instruct` | On genuinely risky moments, generates one short, reassuring sentence the person can say to buy time — never anything alarming. |
| **Ally** | Prepares trusted-contact alerts | `Llama-3.1-8B-Instruct` | Periodically inspects the risk timeline; if average risk stays high across a window, drafts a calm SMS to a family member. |
| **Scribe** | Captures the incident record | `Llama-3.1-8B-Instruct` | Aggregates the call's key moments and renders a formal PDF incident report (Summary, Tactics Used, Key Moments, Recommended Actions). |

An **Orchestrator** module maps each detected tactic to a risk score, records it on the
RedisTimeSeries risk timeline, and publishes the alert that the downstream agents react to.

## Redis as the nervous system

Redis is not just a cache here — it is the messaging fabric, the memory, and the real-time
analytics engine. The Nightwatchman uses a broad slice of Redis data structures, each chosen
for a specific job:

| Data structure | Key(s) | Purpose |
| --- | --- | --- |
| **Streams + consumer groups** | `guardian:transcript` (group `agents`) | Durable transcript backbone; fans every message out to all agents concurrently. |
| **Pub/Sub** | `guardian:alerts`, `guardian:transcripts`, `guardian:coaching`, `guardian:verification`, `guardian:ally` | Pushes live insights to the WebSocket-backed console. |
| **TimeSeries** | `guardian:risk_timeline` | Tracks the risk score over the life of the call; powers the risk gauge and the Ally's escalation logic. |
| **Bloom filter** | `guardian:known_scammers` | Probabilistic, microsecond-latency screening of inbound numbers against a blocklist. |
| **Vector Sets** | `guardian:playbooks` | Semantic matching of utterances to known scam playbooks via embedding similarity (`VADD` / `VSIM`). |
| **Hashes** | `guardian:tactic:*`, `guardian:verification:*`, `guardian:coaching:*` | Per-message analysis results, enabling full state replay on reconnect. |
| **Sorted sets** | `guardian:victim_recent` | Time-windowed dedupe so the victim's own speech is never mistaken for the caller's. |
| **Strings** | `guardian:call_active`, `guardian:ally_alert` | Lightweight call session and alert state flags. |

A `/redis-intelligence` endpoint exposes a live snapshot of this activity for an
observability panel in the UI.

> **Note:** the Bloom filter, TimeSeries, and Vector Set features require **Redis 8** (or
> Redis Stack). See [Getting started](#getting-started).

## Latency

Protecting someone mid-call is only useful if the system keeps pace with the conversation.
The pipeline is built around Redis's in-memory data structures and concurrent agent workers
to keep the time from "words spoken" to "insight on screen" low.

<p align="center">
  <img src="frontend/public/static/latency-diagram.png" alt="The Nightwatchman latency breakdown" width="900" />
</p>

## Tech stack

- **Backend:** Python, [FastAPI](https://fastapi.tiangolo.com/), Uvicorn, asyncio
- **Data / messaging:** [Redis 8](https://redis.io/) — Streams, Pub/Sub, TimeSeries, Bloom,
  Vector Sets — via `redis-py` and `redisvl`
- **AI:** [W&B Inference](https://wandb.ai/) (Llama 3.1 / 3.3), OpenAI embeddings &
  Whisper, [LangGraph](https://github.com/langchain-ai/langgraph)
- **Observability & eval:** [W&B Weave](https://weave-docs.wandb.ai/)
- **Telephony:** [Twilio](https://www.twilio.com/) Programmable Voice + Media Streams
- **Reporting:** ReportLab (PDF)
- **Frontend:** React + Vite

## Repository layout

```
TheNightwatchman/
├── guardian/                  # FastAPI backend + agents
│   ├── main.py                # App, routes, WebSocket, agent worker lifecycle
│   ├── redis_client.py        # Redis primitives: streams, bloom, vector sets, timeseries
│   ├── redis_intelligence.py  # Live Redis activity snapshot for the UI
│   ├── agents/                # Sentinel, Verifier, Coach, Ally, Scribe, Orchestrator
│   ├── ingestion/             # Twilio media stream, audio upload (Whisper), simulator
│   └── reports/               # Generated incident PDFs
├── evals/                     # Weave-based tactic-classification evaluation harness
├── frontend/                  # React + Vite live monitoring console
│   └── public/static/         # System design + latency diagrams
└── docs/                      # Design specs
```

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis 8+ (or Redis Stack) — required for Bloom filters, TimeSeries, and Vector Sets
- API keys: a W&B account (inference + Weave) and an OpenAI key (embeddings + Whisper).
  Twilio credentials are optional and only needed for live phone calls.

### 1. Start Redis

The quickest path with all required modules:

```bash
docker run -d --name nightwatch-redis -p 6379:6379 redis:8
```

### 2. Configure the backend

```bash
cd guardian
cp .env.example .env
# Fill in WANDB_API_KEY, OPENAI_API_KEY, REDIS_HOST/PORT, and (optionally) Twilio values
```

| Variable | Required | Description |
| --- | --- | --- |
| `WANDB_API_KEY` | ✅ | W&B Inference + Weave authentication |
| `WANDB_BASE_URL` | ✅ | OpenAI-compatible inference endpoint (defaults to W&B Inference) |
| `OPENAI_API_KEY` | ✅ | Embeddings (playbook vectors) and Whisper transcription |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | ✅ | Redis connection |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` / `TARGET_PHONE_NUMBER` | ⬜ | Live outbound calls |
| `NGROK_URL` | ⬜ | Public tunnel for Twilio media-stream webhooks |

### 3. Run the backend

```bash
cd guardian
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

On startup the app seeds the known-scammer Bloom filter and the scam-playbook Vector Set,
then launches the Sentinel, Verifier, Coach, Ally, and Scribe workers.

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open the printed Vite URL (default `http://localhost:5173`). The console connects to the
backend WebSocket at `ws://localhost:8000/ws`.

## Running a call

There are three ways to feed a conversation into the system:

- **Simulated call (no telephony needed)** — replays a realistic grandparent-scam script.
  Great for demos and development:

  ```bash
  curl -X POST http://localhost:8000/simulate
  ```

- **Your own voice** — record/upload audio from the console; it is transcribed with Whisper
  and added to the call as the "victim" side.

- **Live Twilio call** — with Twilio configured and a public tunnel running, start an
  outbound call whose audio is streamed in over a Media Stream:

  ```bash
  curl -X POST http://localhost:8000/start-twilio-call
  ```

When a scam outcome is reached, the Scribe produces a downloadable PDF incident report.

## API reference

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness + Redis connectivity check |
| `GET` | `/redis-intelligence` | Live snapshot of Redis activity for the UI panel |
| `POST` | `/simulate` | Replay the built-in sample scam call |
| `POST` | `/reset-call` | Reset state for a new live call |
| `POST` | `/end-call` | Finalize the call and generate the incident report |
| `POST` | `/transcribe-user` | Transcribe uploaded victim audio (Whisper) |
| `GET` | `/twilio-status` | Whether Twilio is configured |
| `POST` | `/start-twilio-call` | Start an outbound Twilio call |
| `POST` | `/twilio/incoming` | Twilio voice webhook (TwiML) |
| `GET` | `/download-report/{timestamp}` | Download a generated incident PDF |
| `WS` | `/ws` | Live transcript, risk, verification, coaching, and ally events |
| `WS` | `/twilio/media` | Twilio Media Stream ingestion |

## Evaluation

Tactic classification is evaluated with a Weave evaluation harness over a labeled set of
utterances:

```bash
cd evals
python evaluate.py
```

This reports classification accuracy and traces every prediction in Weave, so model and
prompt changes can be compared over time.

## Privacy posture

The Nightwatchman is built around calm, family-focused assistance rather than surveillance:

- Clean conversations can be discarded — call state is cleared between sessions.
- Reports are generated only when a call actually warrants one.
- Alerts are designed to reassure and prompt a check-in, never to cause panic.

---

<p align="center"><em>The Nightwatchman — a trusted voice beside every call.</em></p>
