from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer("verialign")
    _otel_available = True
except ImportError:
    _tracer = None
    _otel_available = False


def emit_genai_span(
    request_payload: dict,
    response_payload: dict,
    provider: str | None = None,
    trust_score: float | None = None,
    trust_components: dict | None = None,
) -> None:
    if not _otel_available or not _tracer:
        return

    model = response_payload.get("model") or request_payload.get("model", "")
    usage = response_payload.get("usage", {})
    choices = response_payload.get("choices", [])

    finish_reasons = []
    for choice in choices:
        fr = choice.get("finish_reason")
        if fr:
            finish_reasons.append(fr)

    with _tracer.start_as_current_span("gen_ai.chat") as span:
        span.set_attribute("gen_ai.system", provider or "unknown")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.response.model", model)

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if prompt_tokens:
            span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
        if completion_tokens:
            span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
        if prompt_tokens or completion_tokens:
            span.set_attribute("gen_ai.usage.total_tokens", prompt_tokens + completion_tokens)

        response_id = response_payload.get("id", "")
        if response_id:
            span.set_attribute("gen_ai.response.id", response_id)

        if finish_reasons:
            span.set_attribute("gen_ai.response.finish_reasons", finish_reasons)

        if trust_score is not None:
            span.set_attribute("gen_ai.eval.trust_score", trust_score)
            if trust_components:
                for k, v in trust_components.items():
                    if isinstance(v, (int, float)):
                        span.set_attribute(f"gen_ai.eval.trust_{k}", v)
