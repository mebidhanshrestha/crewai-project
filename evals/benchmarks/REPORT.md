# Token optimisation report: Jyotisha Council

Monitoring: LangSmith (OpenTelemetry tracing of every agent and OpenAI call).
Model: `gpt-5-mini`. Date: 18 October 2026.

## Method

The same benchmark (`evals/benchmark.py`) ran before and after the optimisation: a greeting,
plus a full reading in English, Japanese and Nepali (each reading = giving birth details, then
a question). Every run was traced to its own LangSmith project (`jyotisha-baseline`,
`jyotisha-optimized`), and every reading was checked for correctness: cited rules were really
matched by the rule engine, and the reading is in the person's language.

The baseline is the orchestrator version with no token work at all (model-default reasoning).
The optimisations were chosen from the baseline's LangSmith data, then measured the same way.

## Results

| | Baseline | Optimised | Change |
|---|---|---|---|
| Total tokens (LangSmith) | 69,108 | 43,205 | **-37%** |
| Input tokens | 48,401 | 36,694 | -24% |
| Output tokens (mostly hidden reasoning) | 20,707 | 6,511 | **-69%** |
| Tokens per reading | 19,727 | 13,897 | **-30%** |
| Time per reading | 77 s | 32 s | **-59%** |
| LLM time (LangSmith) | 236 s | 97 s | -59% |
| LLM calls | 35 | 38 | +3 (smaller calls) |
| All readings correct | yes | yes | |

Tokens per agent (sum over the three readings):

| Agent | Baseline | Optimised | Change |
|---|---|---|---|
| Parashar (orchestrator) | 25,831 | 21,813 | -16% |
| Guardian | 7,811 | 2,998 | -62% |
| Shastra | 7,088 | 3,835 | -46% |
| Ganita | 4,404 | 2,495 | -43% |
| Smriti | 0 (skipped) | 1,236 | called this time |

## What the baseline showed, and what changed

1. **Output tokens were 30% of the total, almost all hidden reasoning** (a reading's visible text
   is about 800 tokens). Reasoning effort is now `low`, and `minimal` for Ganita and Smriti,
   which only fetch data. Biggest single effect: output -69%, time -59%.
2. **The orchestrator was 57% of reading tokens**, because every orchestration step re-sends its
   instructions, the tool definitions, the history and all specialist results so far.
   - Instructions rewritten 42% shorter, keeping every rule.
   - Tool descriptions shortened; history window cut from 16 to 8 messages.
   - The Guardian handoff now ends the turn with its result, removing the orchestrator's extra
     call that only said "anything else?". A rejected draft still goes back to the orchestrator.
3. **Tool outputs were verbose.** The chart is now 3 compact lines instead of indented JSON
   (1,331 to 333 characters); rule matches are compact JSON without the classical rule name;
   Smriti gets past questions and outcomes, not full past answers.

## Monitoring fixes found along the way

- **CrewAI over-counted tokens 5x** when agents share one LLM object (`result.token_usage` sums
  per agent). Usage is now read from the LLM's own counter, and it matches LangSmith exactly
  (43,205 both).
- **LangSmith first showed a flat list of OpenAI calls**: CrewAI's agent spans only exist inside
  a Crew, and the orchestrator calls agents directly. Each agent's work is now wrapped in a named
  span, so traces show the tree: Parashar → Ganita / Shastra / Smriti / Guardian.

## A correctness bug the benchmark caught

The first optimised run produced a Nepali reading in the wrong language. The cause was
architectural, not the optimisation: "reply in the language the person writes in" lived in the
web API layer, so any other path (tests, benchmark) depended on the orchestrator remembering to
save the language. It now lives in the chat turn itself; the re-run was fully correct.

## Caveats

- Three readings per run: LLM outputs vary, so treat the percentages as indicative.
- The orchestrator is still 76% of tokens. That is the price of a central agent that re-reads
  the conversation at each handoff; the next steps would be prompt caching of the static
  instructions, summarising specialist results before they enter its context, or deterministic
  routing for the fixed part of the sequence.
- The orchestrator called Smriti in the optimised run where it had skipped it before: it
  decides per question, which is the intended behaviour, but it makes per-agent totals noisier.

Raw data: `baseline.json`, `optimized.json`. Reproduce:
`cd jyotisha_council && python ../evals/benchmark.py <label>`, then
`python ../evals/langsmith_report.py jyotisha-<label>`.
