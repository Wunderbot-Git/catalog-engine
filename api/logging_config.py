import json
import logging
import sys
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter with context fields."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include context fields if set
        for field in ("job_id", "sku_id", "version_id", "user_email", "duration_ms"):
            val = getattr(record, field, None)
            if val is not None:
                log[field] = str(val)

        if record.exc_info and record.exc_info[1]:
            log["exception"] = self.formatException(record.exc_info)

        return json.dumps(log)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet down noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter:
    """Return a logger adapter that accepts extra context fields."""
    return logging.LoggerAdapter(logging.getLogger(name), {})
