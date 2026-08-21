"""Structured and secret-redacting logging for AILEN."""

import json
import logging
import re
from typing import Any

from ailen.core.config import LoggingConfig

# Patterns matching sensitive information in logs
SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE),
    re.compile(r"(sk-[A-Za-z0-9_\-]{15,})", re.IGNORECASE),
    re.compile(r'(["\']?(?:password|api_key|token|secret|access_token)["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE),
    re.compile(r"(--password(?:=|\s+))([^\s]+)", re.IGNORECASE),
]


def redact_secrets(message: str) -> str:
    """Redact sensitive credentials, keys, and tokens from log messages."""
    result = message
    # Redact Bearer tokens
    result = SECRET_PATTERNS[0].sub(r"\1[REDACTED]", result)
    # Redact OpenAI / generic sk- keys
    result = SECRET_PATTERNS[1].sub(r"sk-[REDACTED]", result)
    # Redact key/value pairs (password, token, etc.)
    result = SECRET_PATTERNS[2].sub(r"\1[REDACTED]\3", result)
    # Redact CLI args
    result = SECRET_PATTERNS[3].sub(r"\1[REDACTED]", result)
    return result


class SecretRedactingFormatter(logging.Formatter):
    """Custom logging formatter that strips sensitive patterns."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None, json_format: bool = False):
        super().__init__(fmt, datefmt)
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        # Format original message
        orig_msg = record.getMessage()
        redacted_msg = redact_secrets(orig_msg)

        if self.json_format:
            log_payload: dict[str, Any] = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "name": record.name,
                "message": redacted_msg,
                "module": record.module,
                "line": record.lineno,
            }
            if record.exc_info:
                log_payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_payload, ensure_ascii=False)

        record_copy = logging.makeLogRecord(record.__dict__)
        record_copy.msg = redacted_msg
        record_copy.args = ()
        return super().format(record_copy)


def setup_logging(config: LoggingConfig | None = None) -> logging.Logger:
    """Initialize root and application loggers with AILEN formatting."""
    cfg = config or LoggingConfig()
    level = getattr(logging, cfg.level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    fmt_str = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    formatter = SecretRedactingFormatter(
        fmt=fmt_str,
        datefmt="%Y-%m-%d %H:%M:%S",
        json_format=cfg.json_format,
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    if cfg.log_file:
        try:
            file_handler = logging.FileHandler(cfg.log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            root_logger.addHandler(file_handler)
        except OSError as e:
            root_logger.warning("Could not open log file %s: %s", cfg.log_file, e)

    return logging.getLogger("ailen")
