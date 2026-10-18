"""The Jyotisha Council: 5 agents, sequential process, soft handoffs via task context."""

import json
import os
import time
from datetime import datetime
from typing import Callable

from crewai import LLM, Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from guardrails import make_evidence_guardrail, make_safety_guardrail
from store import DATA, append_prediction
from tools import ChartCalculatorTool, LedgerRecallTool, RuleLookupTool, new_state

METRICS_PATH = DATA / "metrics.jsonl"

# Task name -> agent key, in council order.
PIPELINE = [
    ("calculate_chart", "ganita"),
    ("find_rules", "shastra"),
    ("recall_memory", "smriti"),
    ("draft_answer", "parashar"),
    ("final_review", "guardian"),
]


def make_llm(effort: str | None = None) -> LLM:
    """effort overrides REASONING_EFFORT for one agent (e.g. "minimal" for data-fetching agents)."""
    model = os.getenv("LLM_MODEL", "openai/gpt-5-mini")
    # Reasoning models spend most of their output tokens "thinking". These tasks are short and
    # well-specified, so low effort keeps cost and latency down. REASONING_EFFORT= (empty)
    # turns this off everywhere, which is how the baseline benchmark was measured.
    default = os.getenv("REASONING_EFFORT", "low")
    effort = (effort or default) if default else None
    if effort and model.split("/")[-1].startswith(("gpt-5", "o1", "o3", "o4")):
        return LLM(model=model, reasoning_effort=effort)
    return LLM(model=model)


@CrewBase
class JyotishaCouncil:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self, state: dict, verbose: bool = True, task_callback=None):
        self.state = state  # this consultation only: birth details, chart, matched rules
        self.verbose = verbose
        self.task_callback = task_callback  # called with each TaskOutput
        self.llm = make_llm()

    # --- Agents: no delegation, each one does a single job with its own tool ---

    @agent
    def ganita(self) -> Agent:
        return Agent(config=self.agents_config["ganita"], tools=[ChartCalculatorTool(state=self.state)],
                     llm=self.llm, allow_delegation=False, max_iter=3, verbose=self.verbose)

    @agent
    def shastra(self) -> Agent:
        return Agent(config=self.agents_config["shastra"], tools=[RuleLookupTool(state=self.state)],
                     llm=self.llm, allow_delegation=False, max_iter=4, verbose=self.verbose)

    @agent
    def smriti(self) -> Agent:
        return Agent(config=self.agents_config["smriti"], tools=[LedgerRecallTool(state=self.state)],
                     llm=self.llm, allow_delegation=False, max_iter=3, verbose=self.verbose)

    @agent
    def parashar(self) -> Agent:
        return Agent(config=self.agents_config["parashar"], llm=self.llm,
                     allow_delegation=False, verbose=self.verbose)

    @agent
    def guardian(self) -> Agent:
        return Agent(config=self.agents_config["guardian"], llm=self.llm,
                     allow_delegation=False, verbose=self.verbose)

    # --- Tasks: `context` is the soft handoff, each agent reads the notes it needs ---

    @task
    def calculate_chart(self) -> Task:
        return Task(config=self.tasks_config["calculate_chart"])

    @task
    def find_rules(self) -> Task:
        return Task(config=self.tasks_config["find_rules"], context=[self.calculate_chart()])

    @task
    def recall_memory(self) -> Task:
        return Task(config=self.tasks_config["recall_memory"])

    @task
    def draft_answer(self) -> Task:
        return Task(
            config=self.tasks_config["draft_answer"],
            context=[self.calculate_chart(), self.find_rules(), self.recall_memory()],
            guardrail=make_evidence_guardrail(self.state),
            guardrail_max_retries=2,
        )

    @task
    def final_review(self) -> Task:
        return Task(
            config=self.tasks_config["final_review"],
            context=[self.draft_answer()],
            guardrail=make_safety_guardrail(self.state),
            guardrail_max_retries=2,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            max_rpm=int(os.getenv("MAX_RPM", "30")),  # lower it for rate-limited free tiers
            verbose=self.verbose,
            task_callback=self.task_callback,
        )


def run_council(name: str, birth: dict, question: str, language: str = "English",
                on_event: Callable[[str, dict], None] | None = None, verbose: bool = False) -> dict:
    """Run one reading end to end and save it to the Prediction Ledger.

    on_event("agent", {"agent", "state", "output"?}) reports each handoff as it happens.
    Returns the approved answer, chart, matched rules, evidence strength and metrics.
    """
    emit = on_event or (lambda event, data: None)
    state = new_state(birth, language)
    names = [t for t, _ in PIPELINE]
    started = last = time.perf_counter()
    timings: dict[str, float] = {}
    tokens: dict[str, int] = {}
    council = JyotishaCouncil(state, verbose=verbose)
    # All five agents share one LLM object. CrewAI's result.token_usage sums usage per agent
    # and so counts every call five times; read the shared LLM's counter directly instead.
    usage = council.llm.get_token_usage_summary
    last_tokens = 0

    def on_task_done(output) -> None:
        nonlocal last, last_tokens
        now, used = time.perf_counter(), usage().total_tokens
        agent_key = dict(PIPELINE).get(output.name)
        timings[agent_key] = round(now - last, 1)
        tokens[agent_key] = used - last_tokens
        last, last_tokens = now, used
        emit("agent", {"agent": agent_key, "state": "done", "output": output.raw})
        if output.name in names and names.index(output.name) + 1 < len(names):
            emit("agent", {"agent": PIPELINE[names.index(output.name) + 1][1], "state": "working"})

    emit("agent", {"agent": PIPELINE[0][1], "state": "working"})
    council.task_callback = on_task_done
    result = council.crew().kickoff(inputs={
        "name": name, "question": question, "language": language,
    })
    answer = result.raw.strip()
    append_prediction(name, question, answer, sorted(state["matched_rule_ids"]))

    total = usage()
    metrics = {
        "seconds_total": round(time.perf_counter() - started, 1),
        "seconds_by_agent": timings,
        "tokens_by_agent": tokens,
        "llm_calls": total.successful_requests,
        "prompt_tokens": total.prompt_tokens,
        "completion_tokens": total.completion_tokens,
        "total_tokens": total.total_tokens,
        "model": os.getenv("LLM_MODEL", "openai/gpt-5-mini"),
    }
    with METRICS_PATH.open("a") as f:  # one line per reading, for cost and latency analysis
        f.write(json.dumps({"timestamp": datetime.now().isoformat(timespec="seconds"), **metrics}) + "\n")

    return {
        "answer": answer,
        "chart": state["chart"],
        "rules": state["matches"],
        "strength": state["strength"],
        "metrics": metrics,
    }


if __name__ == "__main__":
    # `python crew.py` runs the interactive consultation.
    from main import main

    main()
