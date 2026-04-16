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
import sys

from opentelemetry.trace import get_current_span
from pythonjsonlogger import jsonlogger


class OTelFilter(logging.Filter):
    def filter(self, record):
        try:
            span = get_current_span()
            ctx = span.get_span_context()
            trace_id = ""
            span_id = ""
            if ctx and ctx.trace_id:
                trace_id = format(ctx.trace_id, "032x")
            if ctx and ctx.span_id:
                span_id = format(ctx.span_id, "016x")
            record.trace_id = trace_id
            record.span_id = span_id
        except Exception:
            record.trace_id = ""
            record.span_id = ""
        return True


class Logger:
    """
    Structured JSON Logger with OpenTelemetry trace/span enrichment.
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(f"{name}")
        self.logger.setLevel(logging.INFO)

        # JSON formatter for structured logs (easier ingestion into Loki)
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s %(trace_id)s %(span_id)s"
        )

        # Console handler
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(OTelFilter())

        # File handler
        file_handler = logging.FileHandler(f"{name}.log")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(OTelFilter())

        # Ensure no duplicate handlers
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        self.logger.addHandler(stream_handler)
        self.logger.addHandler(file_handler)

    def debug(self, msg: str):
        self.logger.debug(msg)

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def critical(self, msg: str):
        self.logger.critical(msg)
