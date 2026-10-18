"""LangSmith tracing via OpenTelemetry (https://docs.langchain.com/langsmith/trace-with-crewai).

When LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set, every CrewAI agent, task and
tool call, and every OpenAI request with its token counts, is sent to the LangSmith
project named by LANGSMITH_PROJECT. Without those variables this module does nothing.
"""

import os

_provider = None


def setup_tracing() -> bool:
    """Instrument CrewAI and OpenAI once per process. Returns True if tracing is on."""
    global _provider
    if _provider is not None:
        return True
    if os.getenv("LANGSMITH_TRACING", "").lower() != "true" or not os.getenv("LANGSMITH_API_KEY"):
        return False

    from langsmith.integrations.otel import OtelSpanProcessor
    from opentelemetry import trace
    from opentelemetry.instrumentation.crewai import CrewAIInstrumentor
    from opentelemetry.instrumentation.openai import OpenAIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(OtelSpanProcessor())
    CrewAIInstrumentor().instrument(tracer_provider=provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    _provider = provider
    return True


def flush_traces() -> None:
    """Send buffered spans now. Serverless functions can freeze before a background flush."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=10_000)


def agent_span(name: str):
    """A named span around one agent's work; LLM calls inside nest under it in LangSmith."""
    from contextlib import nullcontext

    if _provider is None:
        return nullcontext()
    return _provider.get_tracer("jyotisha").start_as_current_span(name)
