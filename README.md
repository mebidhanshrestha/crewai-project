# Jyotisha Council: a 5-agent CrewAI chat app

A small working version of the AI Jyotisha concept. You **chat** with Parashar, the council's
host, in **English, Nepali or Japanese**. Say hello, share your birth details in your own words,
and ask a question. When a question needs a real reading, Parashar **hands off** to a council of
specialist agents. The maths and the rules are deterministic code and the LLM only explains them.
Every claim cites a rule the engine actually matched, confidence is calibrated against a
population of charts, and a Guardian agent reviews the reading before you see it.

Built with **CrewAI 1.15**, **OpenAI** (`gpt-5-mini`), **FastAPI** and **React**. Any
CrewAI-supported model works by changing one line in `.env`.

## Quick start

```bash
cd crewai-project
source .venv/bin/activate        # once per terminal; your prompt shows (.venv)
cd jyotisha_council
uvicorn api:app --port 8000
```

Open **http://localhost:8000** and say hello. Stop the server with `Ctrl + C`.

A typical conversation:

> **You:** hello
> **Parashar:** Hello, I'm Parashar from the Jyotisha Council. I host a council of five specialists... What's your name?
> **You:** I'm Sita, born 12 April 1998 at 6:30 am in Kathmandu
> **Parashar:** Thanks, I've saved your details. What would you like the council to look at?
> **You:** Should I take the Japan job offer?
> *(the council works live in the chat: Ganita → Shastra → Smriti → Parashar → Guardian)*
> **Council reading:** *Moderate evidence · more specific than 62% of charts.* Leaning positive...
> ✦ Your Jupiter period: growth and learning · ◆ Career progress that needs persistence (tap any reason to see why)

**Terminal version (no browser):** `python crew.py` asks for the details one by one and prints the reading.

## The web app

- **Chat** with Parashar in English, Nepali or Japanese. Dates and times can be written naturally.
- **Live council:** when a reading starts, a card in the chat shows each agent working and handing off.
- **Evidence Mode:** each reason is a plain-language tag (✦ supportive, ◆ caution). Tapping it shows
  the rule, the chart evidence, **how common it is** ("fits about 24% of people") and the rule code.
- **Calibrated confidence:** a badge such as "Moderate evidence · career: more specific than 62% of charts".
- **Chart** and **"How the council reached this"** (every agent's handoff note, seconds per agent,
  LLM calls and tokens) fold out under each reading.
- **Side panel:** council status, the details collected, the Prediction Ledger with
  "Came true? Yes / No", a **Forget me** button, and the guardrails. On phones it opens from **Council**.
- **Returning visitors:** say your name and Smriti recalls your (encrypted) birth details;
  Parashar asks whether earlier readings came true.
- Light and dark themes follow your system setting.

**While editing the frontend**, run the API as above and, in a second terminal,
`cd frontend && npm run dev`, then open http://localhost:5173 (it reloads on save and forwards
`/api` to port 8000). Run `npm run build` when done so port 8000 serves the new version.

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` | One chat turn. Streams Server-Sent Events: `thinking`, `profile`, `council_started`, `agent`, `reading`, `reply`, `end` (or `error`) |
| `GET /api/ledger?name=` | A person's past readings |
| `POST /api/ledger/{id}/outcome` | Record `happened` / `did_not_happen` |
| `DELETE /api/person?name=` | Delete-on-request: birth details, readings and chat transcripts |

## How it works

```
 you ──► [Input guardrail, en/ne/ja] ── blocked? → kind refusal in your language, no LLM call
              │
              ▼
        ┌────────────┐  tools: remember_birth_details, record_reading_feedback, forget_me
        │  Parashar  │  small talk, collects details, decides when to hand off
        │   (host)   │  every reply passes chat_guardrail
        └─────┬──────┘
              │ consult_council(question)   ← the soft handoff
              ▼
  ┌─────────┐  chart  ┌─────────┐  rules + IDs  ┌──────────┐  draft  ┌──────────┐
  │ Ganita  │───────► │ Shastra │─────────────► │ Parashar │───────► │ Guardian │──► reading
  │ (calc)  │         │ (rules) │       ┌─────► │ (writer) │         │ (ethics) │      │
  └────┬────┘         └────┬────┘       │       └────┬─────┘         └────┬─────┘      ▼
       │                   │      ┌─────┴────┐       │                    │     Prediction
  chart_calculator    rule_lookup │  Smriti  │  evidence guardrail   safety guardrail  Ledger
  (Swiss Ephemeris)   + base rates│ (memory) │  (cites matched IDs)  (+ evidence re-check)
                                  └────┬─────┘
                                  ledger_recall
```

| Agent | Job | Tools |
|---|---|---|
| **Parashar** | Hosts the chat; inside the council, writes the reading in Evidence Mode | `remember_birth_details`, `consult_council`, `record_reading_feedback`, `forget_me` |
| **Ganita** | Sidereal chart, nakshatra, Vimshottari dasha | `chart_calculator` (Swiss Ephemeris; takes no arguments) |
| **Shastra** | Matches rules for up to 2 topics and ranks the evidence against 3,000 random charts | `rule_lookup` (`data/rules.json`, `data/base_rates.json`) |
| **Smriti** | Recalls past questions, outcomes and saved birth details | `ledger_recall` (`data/ledger.json`, `data/profiles.enc`) |
| **Guardian** | Removes anything unsafe, keeps citations | none |

### Soft handoffs
- **Host to council:** Parashar decides for itself when a message needs a reading and calls
  `consult_council`. Greetings, small talk and collecting details never reach the council.
- **Inside the council:** agents don't call each other directly. Each task ends with a
  `HANDOFF to <agent>:` note, and CrewAI's `context=[...]` passes those outputs on.
- **On rejection:** when a guardrail rejects a draft, the agent gets the **reason** and rewrites
  it instead of the run crashing.

### Guardrails (all plain code, English / Nepali / Japanese)
1. **Input guardrail:** messages about death, health, legal cases or self-harm are declined before
   any LLM call, with the refusal in the message's language (and a helpline for self-harm).
2. **Evidence guardrail:** Parashar's draft must cite rule IDs, and only IDs Shastra actually matched.
3. **Safety guardrail:** the Guardian's final answer can't contain fatalistic predictions, fear
   language, certainty, prices or paid remedies, **and its citations are checked again**, because
   the Guardian rewrites text.
4. **Chat guardrail:** the same safety check runs on every host reply, including small talk.
5. **Spoofed context:** text in a user message that imitates a `[context]`/`[system]` block is
   stripped; trusted session facts travel only in a system message.

### Why it's built this way
- **The LLM explains and never calculates.** Planet positions come from Swiss Ephemeris and rule
  matches from a rules file. Ganita's tool takes no arguments: it reads the verified birth details
  from the consultation's state, so the LLM can't mistype a date on the way to the ephemeris.
- **The host can't make readings.** It has no chart tools; the only way to answer a life question
  is to hand off to the council.
- **Each reading has its own state** (`tools.new_state`), shared only by that reading's tools and
  guardrails, so concurrent readings never mix.
- **Confidence is calibrated, not counted** (see below).
- **The Prediction Ledger** saves every reading and later asks whether it came true.

## Calibrated confidence (the Barnum problem)

Counting matched rules overstates confidence, because many classical rules fit a large share of
people. `scripts/base_rates.py` computes 3,000 charts (1960–2010, six cities in Nepal and North
India, fixed seed) and records how often each rule fires:

| Rule | Fits | | Rule | Fits |
|---|---|---|---|---|
| Partnerships are well supported | 59% | | Natural leadership at work | 8% |
| A career set to grow steadily | 51% | | A pull toward foreign lands | 9% |
| A sharp, creative mind | 51% | | Spending can outpace gains | 8% |

Each matched rule is weighted by its information, `-log2(share of people)`, and the chart's total
for the topic is ranked against the same population. "Strong" means roughly the top quarter.

| Career confidence | Before (rule count) | After (calibrated) |
|---|---|---|
| strong | 70% of people | 24% |
| moderate | 22% | 33% |
| limited | 8% | 43% |

Nine **caution** rules (e.g. "Spending can outpace gains") balance the supportive ones, and the
writer is told to weigh them equally. Rebuild after changing rules: `python scripts/base_rates.py`.

## Testing and evaluation

**Unit tests** (no API key, about 2 seconds): `cd jyotisha_council && pytest`. 40 tests cover the
ephemeris, dasha sequence, rule labels in three languages, calibration, per-reading state,
guardrails in English, Nepali and Japanese (what must be blocked **and** what must be allowed),
evidence re-checking after the Guardian, encryption at rest and delete-on-request.

**Behaviour evals** (real model, costs a few cents per reading):

```bash
cd jyotisha_council
python ../evals/run_evals.py              # all cases in evals/cases.yaml
python ../evals/run_evals.py greeting_ja  # one case
```

Scripted conversations check what the agents actually do: no handoff on small talk or with missing
details, a handoff when details are complete, readings and replies in Japanese and Nepali, valid
citations, guardrail refusals in three languages, resistance to a spoofed-context upsell, and
forget-me. Results are written to `evals/last_results.json`.

Latest run (`gpt-5-mini`): **12/12 passed**. A full reading averaged **8.3 LLM calls, about
21,900 tokens and 100 seconds**; roughly half the tokens are the model's own reasoning output.
The slowest step is Parashar writing the reading.

> **A measurement bug worth knowing about:** CrewAI's `result.token_usage` sums usage per agent.
> All five agents share one LLM object here, so it counted every call five times (it reported
> about 42 calls and 101,000 tokens per reading). `run_council` reads the shared LLM's counter
> directly, and records tokens per agent from it.

## Metrics

Every reading records total seconds, seconds per agent, LLM calls and tokens. They appear under
"How the council reached this" and are appended to `data/metrics.jsonl` for cost and latency
analysis. The terminal version prints a one-line summary.

## Privacy

- Birth details are **encrypted at rest** (`data/profiles.enc`, Fernet: AES-128 + HMAC). The key
  is `PROFILE_KEY` in `.env`, or is generated once into `data/.profile_key` (git-ignored). In
  production it would live in a secrets manager.
- **Delete-on-request:** say "forget me" in the chat (Parashar asks you to confirm), press
  **Forget me** in the side panel, or call `DELETE /api/person`. It removes the profile, every
  ledger entry and chat transcripts for that name.
- Chat sessions are saved under `data/sessions/` so a server restart doesn't lose a conversation.

## Demo ideas

| Try | What it shows |
|---|---|
| Say `hello`, then `こんにちは` | Parashar introduces itself in each language, no council call |
| Give birth details in plain words, then ask about a job abroad | The handoff, all 5 agents live, labelled evidence, calibrated confidence |
| Tap an evidence tag | "Fits about N% of people": honest about how specific each reason is |
| Open **How the council reached this** | Every agent's handoff note, seconds per agent, tokens |
| Start a **New chat** and give the **same name** | Smriti remembers your details; Parashar asks if the last reading came true |
| Say `When will I die?`, `म कहिले मर्छु?` or `私はいつ死ぬ？` | Input guardrail declines in that language, with no LLM call |
| Say "forget me" | Confirmation, then everything about you is deleted |

## Setup (first time only)

Needs **Python 3.10–3.13** (CrewAI does not support 3.14 yet) and **Node.js 18+**.

```bash
cd crewai-project
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # then paste your key into .env

cd frontend
npm install
npm run build                    # creates frontend/dist, served by the API on port 8000
```

Get an OpenAI API key at https://platform.openai.com/api-keys and add credit under
**Settings → Billing** (a ChatGPT Plus subscription does not include API credit).
A consultation costs a few cents.

## Deploy to Vercel (free Hobby plan)

The repo is ready for Vercel: `vercel.json` builds the React app and serves the FastAPI backend
as one Python function (`api/index.py`) at `/api/*`, with a 300-second limit (a reading takes
about 100 seconds).

1. Push this repo to GitHub.
2. On vercel.com: **Add New → Project → Import** the repo. Keep the defaults (`vercel.json` sets them).
3. Under **Environment Variables** add `OPENAI_API_KEY` (and optionally `LLM_MODEL`, `MAX_RPM`).
4. **Deploy.** Open the URL and say hello.

Good to know:
- **Data is temporary on Vercel.** Readings, saved details and chats are written to `/tmp`, which
  resets when Vercel starts a fresh instance. Fine for a demo; a database would make it permanent.
- **The site is public and uses your OpenAI credit.** Set a monthly spending limit at
  https://platform.openai.com/settings/organization/limits before sharing the link.
- The first request after a quiet period is slower while the function starts.

## Configuration

All settings live in `.env` (never commit it; it is in `.gitignore`):

```bash
OPENAI_API_KEY=your-key-here
LLM_MODEL=openai/gpt-5-mini               # swap provider with one line
# LLM_MODEL=openai/gpt-5                  # stronger, pricier
# LLM_MODEL=anthropic/claude-sonnet-5-5   # needs ANTHROPIC_API_KEY
# LLM_MODEL=gemini/gemini-3.8-flash       # needs GEMINI_API_KEY
# LLM_MODEL=ollama/qwen2.5:7b             # local, free
MAX_RPM=30                                # requests per minute cap
# PROFILE_KEY=...                         # optional Fernet key for encrypted profiles
```

If you switch to the **Gemini free tier**, set `MAX_RPM=4`: it allows only 5 requests per minute
and 20 per day for `gemini-3.8-flash`, which is about one or two consultations a day.

## Other ways to run

```bash
# Everything on one line, no prompts
python main.py --name Sita --date 1998-04-12 --time 06:30 --place Kathmandu \
    --question "Should I take the Japan job offer?" --language Japanese

python main.py --quiet ...      # hide the agents' step-by-step log, show only the answer
```

## Troubleshooting

| Error | Fix |
|---|---|
| `command not found: python` or `No module named crewai` | Run `source .venv/bin/activate` from the `crewai-project` folder first |
| `Missing OPENAI_API_KEY` | Create `.env` from `.env.example` and paste your key |
| `no API credit` | Add credit at https://platform.openai.com/settings/organization/billing (can take a few minutes to apply) |
| `404 ... model is no longer available` | The provider retired that model; set a current one in `LLM_MODEL` |
| `rate limit hit` | Wait about a minute, or lower `MAX_RPM` |
| `profiles.enc cannot be decrypted` | `PROFILE_KEY` changed; restore the old key or delete `data/profiles.enc` |
| `address already in use` | Something already runs on port 8000; stop it or use `--port 8001` |

## Method choices

- **Ayanamsa:** Lahiri. **Houses:** whole-sign from the sidereal Lagna. **Nodes:** mean node
  (Ketu = Rahu + 180°). **Ephemeris:** Swiss Ephemeris, Moshier mode (no data files).
- **Dasha:** Vimshottari, 365.25-day years; antardashas proportional to the 120-year cycle.
  Some traditions use 360-day years, which shifts dates by about 1.5%.
- **Not covered:** divisional charts (D9 and above), aspects, transits, ashtakavarga.

## Files
```
crewai-project/
  .env / .env.example   API key, model, rate limit, optional PROFILE_KEY
  requirements.txt
  evals/                behaviour evals: cases.yaml, run_evals.py, last_results.json
  jyotisha_council/
    crew.py             the council: 5 agents, 5 tasks, handoff wiring, run_council() with metrics
    chat.py             Parashar as chat host: 4 tools, consult_council handoff, saved sessions
    main.py             terminal version
    api.py              FastAPI server for the React chat (streams each turn)
    common.py           places, languages, disclaimers, error messages
    store.py            ledger, encrypted profiles, sessions, delete-on-request
    tools.py            council tools around deterministic code; per-reading state
    guardrails.py       input, evidence, safety and chat guardrails (en/ne/ja)
    config/*.yaml       agent roles, task instructions, host instructions
    astro/ganita.py     Swiss Ephemeris chart + Vimshottari dasha
    astro/shastra.py    rule engine, calibrated evidence strength, labels
    scripts/base_rates.py  builds data/base_rates.json from 3,000 random charts
    data/rules.json     35 starter rules with en/ne/ja labels and tone
    tests/              40 unit tests
  frontend/             React + Vite chat app (src/components: ChatThread, Composer, CouncilProgress,
                        ReadingCard, ChartCard, Sidebar, Ledger)
```

## Limits (on purpose, to keep it basic)
- 35 starter rules, D1 chart only. Rule readings, and the Nepali and Japanese labels, need review
  by an astrologer and native speakers before real use.
- Keyword guardrails are a first line of defence; production would add a multilingual classifier.
- The interface text is in English; readings, replies, labels and refusals follow the user's language.
- Ganita is an LLM agent so every step shares one orchestration and can be observed; in production
  the chart would be computed directly and the agent kept only where judgement is needed.
- A small built-in city list (other places take coordinates). JSON files rather than a database.
