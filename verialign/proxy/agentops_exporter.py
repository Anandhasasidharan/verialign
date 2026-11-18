"""Deliver verification spans to the AgentOps SLO Platform JSON receiver."""

import logging

import httpx
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)
_TRUST_ATTRIBUTE = "gen_ai.eval.trust_score"


class AgentOpsSpanExporter(SpanExporter):
    def __init__(self, endpoint: str, api_key: str) -> None:
        self._endpoint = endpoint
        self._client = httpx.Client(
            timeout=5.0, headers={"X-API-Key": api_key, "Content-Type": "application/json"}
        )

    def export(self, spans) -> SpanExportResult:
        verification_spans = []
        for span in spans:
            attrs = span.attributes or {}
            if _TRUST_ATTRIBUTE not in attrs or span.context is None:
                continue
            resource = span.resource.attributes
            verification_spans.append(
                {
                    "name": "verialign.verification",
                    "kind": 1,
                    "traceId": f"{span.context.trace_id:032x}",
                    "spanId": f"{span.context.span_id:016x}",
                    "startTimeUnixNano": str(span.start_time),
                    "endTimeUnixNano": str(span.end_time),
                    "attributes": [
                        {
                            "key": _TRUST_ATTRIBUTE,
                            "value": {"doubleValue": attrs[_TRUST_ATTRIBUTE]},
                        },
                        {
                            "key": "agentops.agent.id",
                            "value": {
                                "stringValue": resource.get("agentops.agent.id", "verialign")
                            },
                        },
                        {
                            "key": "agentops.environment",
                            "value": {
                                "stringValue": resource.get("agentops.environment", "production")
                            },
                        },
                    ],
                }
            )
        if not verification_spans:
            return SpanExportResult.SUCCESS

        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "verialign"}}
                        ]
                    },
                    "scopeSpans": [{"scope": {"name": "verialign"}, "spans": verification_spans}],
                }
            ]
        }
        try:
            self._client.post(self._endpoint, json=payload).raise_for_status()
        except (httpx.HTTPError, ValueError):
            logger.warning("agentops_trust_export_failed")
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._client.close()
