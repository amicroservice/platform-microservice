# Copyright 2024 Taufik Hidayat authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import start_http_server

DEFAULT_METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))


def setup_observability(service_name: str, logger: logging.Logger):
    """Configure Prometheus metrics endpoint and OpenTelemetry tracing.

    - Starts a Prometheus HTTP server on `METRICS_PORT` for Mimir scraping.
    - Configures an OTLP exporter for tracing (Tempo) and instruments gRPC server.
    """

    # Start Prometheus metrics endpoint
    try:
        start_http_server(DEFAULT_METRICS_PORT)
        logger.info(
            f"{__name__}: Prometheus metrics exposed on port {DEFAULT_METRICS_PORT}"
        )
    except Exception as e:
        logger.warning(f"{__name__}: Failed to start Prometheus HTTP server: {e}")

    # Setup OpenTelemetry tracing
    try:
        otlp_endpoint = os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
        )
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Instrument grpc server to capture spans for incoming RPCs
        try:
            GrpcInstrumentorServer().instrument()
            logger.info(f"{__name__}: gRPC server instrumentation enabled")
        except Exception as e:
            logger.warning(f"{__name__}: gRPC instrumentation failed: {e}")

        logger.info(f"{__name__}: OpenTelemetry configured (OTLP={otlp_endpoint})")
    except Exception as e:
        logger.warning(f"{__name__}: Failed to initialize OpenTelemetry: {e}")
