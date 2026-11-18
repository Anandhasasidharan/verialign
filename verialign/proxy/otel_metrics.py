"""OpenTelemetry lifecycle and bounded-dimension verification metrics."""

import logging
import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from verialign.verification.overlay import PolicyAction

if TYPE_CHECKING:
    from opentelemetry.metrics import Histogram
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)

TRUST_METRIC = "verialign.verification.trust_score"
TRUST_BUCKETS = (0.2, 0.4, 0.6, 0.8)
Operation = Literal["chat", "chat_stream", "verify"]


@dataclass
class VerificationTelemetry:
    tracer_provider: "TracerProvider"
    meter_provider: "MeterProvider"
    tracer: "Tracer"
    trust_histogram: "Histogram"

    def record(
        self, score: float | None, operation: Operation, policy_action: PolicyAction
    ) -> None:
        if score is None or not math.isfinite(score) or not 0 <= score <= 1:
            return
        self.trust_histogram.record(
            score,
            {"verialign.operation": operation, "verialign.policy_action": policy_action},
        )

    def shutdown(self) -> None:
        for provider in (self.meter_provider, self.tracer_provider):
            try:
                provider.shutdown()
            except Exception:
                logger.warning("otel_shutdown_failed")


def create_telemetry(
    agentops_endpoint: str | None, agentops_api_key: str | None
) -> VerificationTelemetry:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": "verialign"})
    readers = []
    if os.getenv("OTEL_METRICS_EXPORTER", "otlp").lower() != "none":
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=readers,
        views=[
            View(
                instrument_name=TRUST_METRIC,
                aggregation=ExplicitBucketHistogramAggregation(boundaries=TRUST_BUCKETS),
            )
        ],
        shutdown_on_exit=False,
    )
    tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
    try:
        if os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower() != "none":
            tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        if agentops_endpoint and agentops_api_key:
            from verialign.proxy.agentops_exporter import AgentOpsSpanExporter

            tracer_provider.add_span_processor(
                BatchSpanProcessor(AgentOpsSpanExporter(agentops_endpoint, agentops_api_key))
            )
        elif agentops_endpoint or agentops_api_key:
            logger.warning("agentops_export_requires_endpoint_and_key")

        return VerificationTelemetry(
            tracer_provider,
            meter_provider,
            tracer_provider.get_tracer("verialign"),
            meter_provider.get_meter("verialign").create_histogram(
                TRUST_METRIC, unit="1", description="Trust score of a completed verification"
            ),
        )
    except Exception:
        try:
            meter_provider.shutdown()
        finally:
            tracer_provider.shutdown()
        raise
