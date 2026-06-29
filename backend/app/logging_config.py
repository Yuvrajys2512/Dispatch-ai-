"""Structured JSON logging for production.

Replaces the default unformatted log lines with a single JSON object per
record so log aggregators (Railway, Fly, Datadog, etc.) can index and filter
on level, logger name, and message without regex parsing.

Call `configure_logging()` once at app startup. In tests this is never called,
so pytest output stays human-readable.
"""

from __future__ import annotations

import json
import logging
import time


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            data["stack"] = self.formatStack(record.stack_info)
        return json.dumps(data, ensure_ascii=False)


def configure_logging(log_level: str = "info") -> None:
    """Switch the root logger to structured JSON output.

    Idempotent: safe to call multiple times (replaces handlers each time).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level.upper())
    # Quiet noisy libraries that flood at DEBUG.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
