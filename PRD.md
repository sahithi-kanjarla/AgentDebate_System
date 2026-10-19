# PRD — Tribunal: A Multi-Agent Debate System

> **For Claude Code:** This is the full spec. Build it **milestone by milestone** (Section 12). After each milestone, stop, run the tests, and summarize what was built before continuing. When this document and reality disagree (e.g., a model name no longer exists), check the provider's current docs, choose the closest equivalent, and note the change in `DECISIONS.md`.

---

## 1. Overview

**Tribunal** takes a question or a piece of text. Several AI agents, each running on a **different free-tier LLM provider**, answer independently. They then anonymously critique each other over multiple rounds, finding mistakes and revising their positions. A judge agent delivers a final decision with a confidence score and a list of the mistakes caught along the way.

It ships with an **evaluation harness** that measures how much accuracy the debate adds over a single model on a public benchmark. That number is the project's headline result.

**Inspiration:** Karpathy's `llm-council` and the "multi-agent debate" research line (Du et al., 2023). Tribunal differs in four ways: true multi-round debate (not one review pass), persona-driven agents, live streaming UI, and a built-in benchmark with honest baselines.

## 2. Goals

1. **Working product:** a user types a question, watches agents debate live, and gets a verdict.
2. **Measured result:** an eval script producing a results table (single model vs. majority vote vs. debate).
3. **$0 cost:** every component runs on free tiers or locally.
4. **Portfolio quality:** clean code, tests, CI, an excellent README, and a public deployed demo.

### Non-goals (v1)
- User accounts/auth
- Paid model support (but the architecture must make adding one trivial)
- Mobile app

## 3. Users & Use Cases

- **Primary:** a recruiter or engineer visiting the demo who wants to understand it in under 30 seconds.
- **Secondary:** the author, running evals and showing results in interviews.

| Mode | Input | Output |
|---|---|---|
| **Answer** | A question ("Is it cheaper to rent or buy in Hyderabad for 5 years?", a math/logic problem) | Final answer + confidence + reasoning + dissent |
| **Review** | A piece of text/claim/short code snippet | List of verified mistakes, severity, and a corrected version |

## 4. Tech Stack (all free)

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Async-native, industry standard, great for interviews |
| LLM calls | **`openai` Python SDK** pointed at each provider's **OpenAI-compatible endpoint** | One client for every provider; no heavy framework |
| Validation | **Pydantic v2** | Structured agent outputs, settings management |
| Streaming | **Server-Sent Events (SSE)** via `sse-starlette` | Live debate updates; simpler than WebSockets |
| Storage | **SQLite** via **SQLModel** | Zero setup; swap to free Postgres later by changing `DATABASE_URL` |
| Rate limiting (public demo) | **slowapi** | Protects free-tier quotas from abuse |
| Frontend | **React + Vite + TypeScript + Tailwind CSS** | Most in-demand frontend stack |
| Frontend state/data | **TanStack Query** + native `EventSource` | Clean data fetching + SSE |
| Visualization | **Custom SVG + D3 (`d3-scale`, `d3-shape`, `d3-sankey`) + Framer Motion**; **Recharts** for small charts | Full control over the neural-network look and animations; layout is computed, not a force simulation, so it stays stable and readable |
| 3D (stretch only) | **react-three-fiber + drei** | Optional "3D neural" mode after everything else ships |
| Testing | **pytest + pytest-asyncio** (backend), **Vitest** (frontend) | Standard |
| Lint/format | **ruff** (Python), **ESLint + Prettier** (TS) | Standard |
| CI | **GitHub Actions** | Free for public repos |
| Packaging | **Docker** (single container: FastAPI serves built frontend) | One deploy target |
| Deployment | **Hugging Face Spaces (Docker SDK, free CPU)**; alternative: Render free tier | Free; good fit for AI demos |

### LLM providers (free tiers — verify current limits and model IDs at build time)

| Role | Provider | Suggested model | Notes |
|---|---|---|---|
| Debater A | Google AI Studio (Gemini API) | current free **Flash** model | OpenAI-compatible endpoint available |
| Debater B | Groq | a Llama 70B-class or `gpt-oss-120b` | Very fast; per-model daily limits |
| Debater C | OpenRouter | a `:free` model (or `openrouter/free` auto-router) | ~50 req/day on free tier |
| Judge | Groq or Gemini | strongest free model available | Must reliably emit JSON |
| Offline/dev | **Ollama** (local) | any small model, e.g. Llama 3.x 8B | Unlimited; used for dev + as fallback |
| Tests | **MockProvider** | — | Deterministic, no network |

Using **different model families** is intentional: diverse models make different mistakes, so they catch each other's errors better than copies of one model.

## 5. Core Flow

```
User input
   │
   ▼
Round 0 — Independent answers (parallel)
   A, B, C each answer alone (no peer visibility)
   │
   ▼
Round 1..N — Critique & revise (parallel per round)
   Each agent sees the OTHER agents' latest answers, anonymized and shuffled
   ("Response 1", "Response 2"). It must:
     - identify specific mistakes in others' answers
     - defend or revise its own answer
     - state its current final answer + confidence (0–100)
   After each round → compute consensus. Stop early if consensus reached.
   │
   ▼
Judge — reads full transcript (anonymized), outputs structured verdict
   │
   ▼
Persist + stream verdict to UI
```

**Defaults:** 3 debaters, max 3 critique rounds, early stop when all agents' normalized final answers match (Answer mode) or the judge-lite check says positions converged (Review mode).

### Anonymization rules
- Agents never see provider/model names, only "Response N."
- Response order is shuffled every round per agent (seeded RNG for reproducibility).
- The judge sees agents as "Debater 1/2/3," not model names.

## 6. Agent Design

### Personas (configurable in `config/agents.yaml`)
- **The Solver:** methodical, step-by-step, shows work.
- **The Skeptic:** assumes something is wrong; hunts for errors, edge cases, hidden assumptions.
- **The Fact-Checker:** focuses on factual claims, units, arithmetic, and logical validity.

### Structured output (every debater, every round), enforced via Pydantic
```json
{
  "reasoning": "string",
  "critiques": [{"target": "Response 2", "issue": "string", "severity": "low|medium|high"}],
  "changed_mind": true,
  "changed_mind_because": "string | null  (quote/describe which critique convinced it; null if unchanged)",
  "final_answer": "string (short, normalized — e.g. '42' or 'Yes')",
  "confidence": 0
}
```

### Judge output
```json
{
  "final_answer": "string",
  "confidence": 0,
  "summary": "2–4 sentence explanation",
  "mistakes_caught": [{"description": "string", "caught_by": "Debater 2", "round": 1}],
  "dissent": "string | null",
  "consensus_reached": true
}
```

**Parsing robustness:** request JSON mode where supported; on parse failure, retry once with a "fix your JSON" message; on second failure, mark that agent's turn `invalid` and continue (the debate must never crash because one agent misbehaved).

Prompts live in `backend/app/prompts/*.md` (not hard-coded) so they're easy to iterate on.

## 7. Functional Requirements

### Backend
- **FR1** `POST /api/debates`: body `{question, mode: "answer"|"review", rounds?: 1–3}` → `{id}`. Validate input length (≤ 4,000 chars).
- **FR2** `GET /api/debates/{id}/stream`: SSE events:
  - `debate_started` `{id, agents: [{label, persona}]}`
  - `agent_thinking` `{round, agent}`
  - `agent_response` `{round, agent, payload}`
  - `critique_edge` `{round, from_agent, to_agent, severity, issue}`. **The server resolves** the shuffled "Response N" label back to the real agent id (it stores the per-recipient shuffle mapping), so the UI can draw edges between the right nodes. Emitted right after the matching `agent_response`.
  - `round_complete` `{round, consensus_score, agreed: bool, clusters: [{cluster_id, normalized_answer, agents: [...]}]}`. Clusters group agents by normalized final answer, which drives node coloring in the graph.
  - `judge_verdict` `{payload}`
  - `error` `{agent?, message, recoverable}`
  - `done` `{stats: {total_tokens, latency_ms, calls}}`
- **FR3** `GET /api/debates/{id}`: full stored transcript + verdict.
- **FR4** `GET /api/debates?limit=20`: recent debates (history page).
- **FR5** `GET /api/agents`: configured agents, personas, and whether each provider is currently reachable. **Provider and model ids are omitted unless `EXPOSE_AGENT_MODELS=true` (local dev):** the lineup is the same for every debate, so listing it publicly would un-anonymize all of them. Models are shown inside a debate only through the reveal (FR15).
- **FR6** `GET /api/health`.
- **FR7** Provider abstraction: `LLMProvider` interface with `complete(messages, json_mode) -> CompletionResult(text, tokens_in, tokens_out, latency_ms)`. Implementations: `OpenAICompatibleProvider` (Gemini/Groq/OpenRouter/Ollama via base_url), `MockProvider`.
- **FR8** Resilience: per-provider retry with exponential backoff + jitter on 429/5xx; per-provider concurrency semaphore; **fallback chain** (e.g., if OpenRouter fails twice → Ollama or another free model), recorded in the transcript.
- **FR9** Response cache keyed on `(provider, model, messages hash)` in SQLite. This is essential for the eval harness to stay within free quotas and be resumable.
- **FR10** Public demo protection, all configurable via env and off by default for local dev (`RATE_LIMIT_ENABLED`): per-IP limits on `POST /api/debates` (default 5/hour, 20/day); a global cap on real debates per UTC day (`GLOBAL_DAILY_CAP`, default 15) because free-tier quotas are shared; a cap on debates running at once (`MAX_CONCURRENT_DEBATES`); client IP taken from `X-Forwarded-For` only when `TRUSTED_PROXY` says how many proxies to trust. Refusals are `429` with `Retry-After` and a JSON body naming the `scope` (`ip_hour`, `ip_day`, `global_day`, `busy`). Reads (replays, streams, the showcase) and reruns that the response cache answers entirely are never counted.

### Frontend
- **FR11** Home: big input box, mode toggle (Answer / Review), 3 example prompts (one math, one factual trap, one opinion), "Start debate" button.
- **FR12** Live debate view: one column per debater with a persona badge. Each round renders as a card inside the column (reasoning collapsed by default; critiques highlighted with severity color; "changed mind" badge). Show a typing/thinking state while waiting.
- **FR13** Consensus meter between rounds (e.g., "2/3 agree").
- **FR14** Verdict card: final answer, confidence bar, summary, **"Mistakes caught" list** (the hero feature), dissent if any.
- **FR15** Reveal button: "Show which model was which" (de-anonymizes after the verdict; fun for demos). The server never sends provider, model or `label_map` in `GET /api/debates/{id}` or the SSE stream (live or replayed); they stay in the database and are served only by `GET /api/debates/{id}/reveal`, for debates that are not running. The reveal is per page view and is not offered on recorded (sanitized) showcase examples. It only says who wrote what; debaters were never told each other's identity.
- **FR16** History page + shareable URL `/debate/{id}`.
- **FR17** Results page: renders the latest eval results table/chart from `eval/results/latest.json`.
- **FR18** Responsive layout; columns stack on mobile. No theme switching: one light theme, with the graph on a fixed dark stage.

### Visualization — "See the debate think"

**Goal:** someone with zero AI background should understand within 30 seconds what is happening and why the final answer is more trustworthy than a single model's.

**Honesty note (must appear in the UI and README):** this visualizes the *reasoning network between agents* (who critiqued whom, who changed their mind, how answers converged). It does **not** show real model internals such as weights or activations; free APIs don't expose them. Never label it as "the model's neurons."

**One renderer, two sources.** All visuals are driven by a pure reducer (`lib/debateState.ts`) that consumes the same ordered event list, whether it arrives live over SSE or is replayed from a stored transcript. This guarantees replay always matches live behavior.

- **VIS1 — Debate Graph (hero visual).** A layered, neural-network-style diagram, laid out left to right on a fixed grid computed with `d3-scale` (no force simulation).
  - Columns: `Question → Round 0 → Round 1 → … → Round N → Judge`. Rows: one per debater.
  - **Nodes** = an agent's answer in a given round. Size = confidence. Ring/fill color = *answer cluster* (agents holding the same normalized answer share a color), so agreement is visible as colors merging across columns. A node that changed its mind flashes and gets a dashed outline. A node waiting on the LLM shows a pulsing "thinking" ring.
  - **Edges:** (a) faint gray edges from an agent's node to its own node in the next round (its memory); (b) **critique edges** crossing between agents, colored and thickened by severity (yellow/orange/red); each draws in with a traveling pulse from critic to target at the moment the `critique_edge` event arrives; (c) at the end, all final nodes feed into the **Judge node**, which glows in proportion to confidence.
  - Hovering an edge shows the issue text. Nodes and edges animate in as SSE events arrive (Framer Motion).
- **VIS2 — Node inspector.** Clicking a node opens a side drawer: reasoning (collapsed by default), critiques given and received, answer before → after, and **"Why did it change its mind?"**, which highlights the specific incoming critique edge(s) using `changed_mind_because`.
- **VIS3 — Plain-English narrator.** A caption bar narrates each event in simple language, e.g. *"The Skeptic found an arithmetic error in Response 2 (severity: high)."* and *"Two of three agents now agree on 42."* Template-based; **no extra LLM calls**. Pausable.
- **VIS4 — Consensus & confidence charts.** Small line chart of agreement per round (e.g. 1/3 → 2/3 → 3/3) and a confidence sparkline per agent (Recharts).
- **VIS5 — Answer-flow diagram.** A Sankey (`d3-sankey`) showing how each distinct answer's supporters change round to round; wrong answers should visibly shrink and the winning answer grow.
- **VIS6 — Replay.** Timeline scrubber with play/pause and 0.5×–4× speed for any finished debate (history pages, shareable URLs, demos, and easy GIF recording).
- **VIS7 — Guided intro & legend.** A skippable 5-step tour on first visit (what a node is, what edges mean, what the colors mean, what the Judge does, how to read the verdict) and an always-available legend.
- **VIS8 — Linked verdict.** Each item in "Mistakes caught" is linked to its critique edge; hovering the item highlights that edge in the graph and vice versa.
- **VIS9 — Eval visuals** (Results page): grouped bar chart of accuracy by condition; a diverging bar showing questions debate **fixed** vs **broke**; an accuracy-vs-cost scatter (API calls per question vs accuracy).
- **VIS10 — Quality bar.** Respect `prefers-reduced-motion` (static graph, no pulses); colorblind-safe palette plus shape/pattern cues for severity (not color alone); smooth at 60fps for up to ~60 nodes; on mobile the graph scrolls horizontally with pinch-zoom while the narrator and verdict stay readable.
- **VIS11 (stretch, only after M7).** Optional 3D mode with react-three-fiber: nodes as glowing spheres in layered planes, critique edges as light beams. Must be a toggle with the 2D graph remaining the default.

**Backend support:** persist enough in `Turn.parsed_json` (including `cluster_id`, resolved critique targets, `changed_mind_because`) that replay needs no extra data.

### Evaluation harness (the resume headline)
- **FR19** `python -m eval.run --dataset gsm8k --n 100 --seed 42` (CLI).
- **FR20** Datasets: **GSM8K** test subset (math, exact-match scoring); optional second: **ARC-Challenge** (multiple choice) or **StrategyQA** (yes/no). Load via Hugging Face `datasets`; cache locally.
- **FR21** Conditions compared on the **same questions**:
  1. **Single model**: each debater's model alone (3 rows)
  2. **Majority vote**: 3 independent answers, majority wins (no debate). *This baseline is essential: it separates the gain from debate itself from the gain of just ensembling.*
  3. **Debate (1 round)**
  4. **Debate (3 rounds)**
- **FR22** Metrics per condition: accuracy, mean API calls, mean tokens, mean latency, and % of questions where debate **fixed** a wrong majority / **broke** a right one.
- **FR23** Outputs: `eval/results/<timestamp>.json`, `latest.json`, a Markdown table auto-inserted into the README between `<!-- EVAL_START -->` / `<!-- EVAL_END -->` markers, and a PNG bar chart (matplotlib).
- **FR24** Quota-aware: resumable (skips cached items), `--max-calls-per-provider` flag, spreads load across providers, and prints an estimated call count before starting with a confirm prompt.

## 8. Non-Functional Requirements

- **Cost:** $0. No feature may require a paid key.
- **Security:** all API keys in `.env` (never committed; provide `.env.example`); keys never reach the frontend; CORS restricted in production.
- **Performance:** first agent token-visible within ~3s on Groq; a full 3-round debate typically < 60s.
- **Reliability:** one failing provider degrades the debate (fallback or skip), never crashes it.
- **Observability:** structured JSON logs (provider, model, latency, tokens, retries) per call.
- **Code quality:** type hints throughout; ruff clean; ≥ 70% backend test coverage on orchestrator/consensus/parsing logic.

## 9. Data Model (SQLModel)

- `Debate(id: uuid, question, mode, status, created_at, config_json, verdict_json, stats_json)`
- `Turn(id, debate_id, round, agent_label, persona, provider, model, prompt_hash, raw_text, parsed_json, valid: bool, tokens_in, tokens_out, latency_ms, fallback_used: bool)`
- `CacheEntry(key_hash, response_text, created_at)`

## 10. Project Structure

```
tribunal/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, serves frontend build in prod
│   │   ├── api/                 # routes: debates, agents, health
│   │   ├── core/                # settings (pydantic-settings), logging
│   │   ├── providers/           # base.py, openai_compat.py, mock.py, registry.py
│   │   ├── debate/              # orchestrator.py, consensus.py, anonymize.py, parsing.py
│   │   ├── prompts/             # debater.md, critique.md, judge.md
│   │   ├── db/                  # models.py, session.py, cache.py
│   │   └── schemas.py
│   ├── config/agents.yaml
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/ (Home, Debate, History, Results)
│       ├── components/ (VerdictCard, DebaterColumn, ...)
│       ├── components/viz/ (DebateGraph, NodeDrawer, Narrator, ConsensusChart, AnswerFlow, ReplayControls, Legend, Tour)
│       ├── hooks/useDebateStream.ts
│       └── lib/ (api.ts, debateState.ts, layout.ts, narrate.ts, palette.ts)
├── eval/
│   ├── run.py, datasets.py, scoring.py, report.py
│   └── results/
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml           # optional: app + ollama
├── .env.example
├── README.md
└── DECISIONS.md
```

## 11. Deployment (free)

- **Primary:** Hugging Face Spaces, Docker SDK. Multi-stage Dockerfile: build the frontend with Node → copy `dist/` into a Python image → FastAPI serves static files + API on one port (Spaces expects port 7860). Keys go in Space **Secrets**.
- **Note:** free-tier disk may be ephemeral; debate history can reset on restart. That's acceptable for a demo. Optional upgrade: a free hosted Postgres (Neon/Supabase) via `DATABASE_URL`.
- **Alternative:** Render free web service (sleeps when idle; first request is slow).
- Add a visible banner on the demo: "Running on free-tier models — may be slow or rate-limited."

## 12. Milestones (build in this order)

| # | Milestone | Done when |
|---|---|---|
| **M1** | Backend skeleton + `MockProvider` + orchestrator + consensus + parsing | `pytest` passes; a full mock debate runs via `POST` + SSE (test with curl) |
| **M2** | Real providers (Gemini, Groq, OpenRouter, Ollama), retries, fallback, cache, logging | A real debate completes with 3 different providers; killing one provider triggers fallback |
| **M3** | Frontend: home, live debate view, verdict card, history | Can run a debate end-to-end in the browser with live streaming |
| **M4** | **Visualization:** `debateState` reducer, Debate Graph (VIS1), node inspector (VIS2), narrator (VIS3), legend; add `critique_edge` + cluster data to the backend | A live debate animates as a layered graph with traveling critique pulses; clicking a node explains why it changed its mind; reducer has unit tests |
| **M5a** | Frontend: consensus/confidence charts (VIS4), answer flow (VIS5), replay (VIS6), tour (VIS7), linked verdict (VIS8), mobile/a11y polish (VIS10), Showcase of recorded examples | Replay of a stored debate matches the live run (state at position k equals the reducer over the first k events); reduced-motion works; charts have text alternatives; showcase replays with no model calls |
| **M5b** | Backend + UI: Review mode, model reveal with server-side withholding of provider/model and `label_map` until the reveal, rate limiting (FR10), replace placeholder showcase files with real recordings | Both modes work; the browser never receives provider/model/`label_map` before the reveal; rate limit returns 429 with friendly UI message |
| **M6** | Eval harness + results page + eval visuals (VIS9) + README auto-table + chart | `eval.run --n 100` completes within free quotas (using cache/resume across days if needed) |
| **M7** | Docker + CI + deploy to HF Spaces + README (with demo GIF of the graph) | Public URL works; CI green; README has demo GIF, architecture diagram, results table |
| **M8 (stretch)** | 3D mode (VIS11) | Toggle works; 2D remains default; no performance regression |

## 13. README Requirements (recruiters read this first)

1. One-line pitch + **demo link** + **GIF of the Debate Graph animating** at the very top (this is the most shareable asset in the project).
2. **Results table** (auto-generated) with a one-sentence honest takeaway, including where debate *didn't* help.
3. Architecture diagram (Mermaid).
4. "How it works" (the round flow, anonymization, judge).
5. Engineering highlights: provider abstraction, fallback, caching, SSE, structured output recovery.
6. Run locally in 3 commands (with Ollama-only option needing zero API keys).
7. Limitations & future work.

## 14. Success Metrics

- Deployed public demo, working end-to-end.
- Eval on ≥ 100 GSM8K questions with all baselines reported honestly.
- CI green; test coverage target met.
- Resume bullet supported by real numbers, e.g.: *"Built Tribunal, a multi-agent debate system orchestrating 3 free-tier LLMs (Gemini, Llama via Groq, OpenRouter) with anonymized multi-round critique; improved GSM8K accuracy from X% (best single model) / Y% (majority vote) to Z% across 100 questions. FastAPI, React, SSE, Docker, deployed on Hugging Face Spaces."*

## 15. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Free-tier rate limits / quota changes | Cache, resume, per-provider limits, fallback to Ollama, config-driven model IDs |
| Model IDs get deprecated | All model IDs in `agents.yaml`; `/api/agents` health check flags broken ones |
| Agents return malformed JSON | JSON mode + one repair retry + `invalid` turn handling |
| Debate doesn't beat majority vote | Report it honestly; that's still a credible, interview-worthy finding. Try persona/prompt tweaks and log them in `DECISIONS.md` |
| Agents converge on a wrong answer (groupthink) | Skeptic persona; require critiques before agreeing; track the "broke a right answer" metric |
| Public demo abuse | IP rate limits, input length caps, demo banner |
| Visualization becomes a time sink | Ship the 2D graph + reducer first (M4), keep 3D strictly as a post-launch stretch; use computed grid layout, not physics |
| Visual misread as "real model internals" | Honesty note in UI and README; label it the "reasoning network" |

## 16. Future Work (post-v1)
- Agents with tools (web search, Python calculator) for fact-checking
- User-defined personas and number of agents
- Bring-your-own-key for paid models
- Streaming token-by-token inside each card