"""
Structlog configuration for the mail-classifier application.

Usage — call setup_logging() once at application startup (in graph.py or
orchestrator.py __main__ block). Every other module just does:

    import structlog
    logger = structlog.get_logger(__name__)

Behaviour by environment:
  - development : human-readable coloured output to console + JSON to file
  - production  : JSON to both console and file (machine-parseable)

Log level controlled by:
  Priority: LOG_LEVEL env var → ENV-based default (DEBUG in dev, INFO in prod)
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import structlog

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Third-party loggers that are too noisy — capped at WARNING
NOISY_LOGGERS = [
    "googleapiclient",
    "google.auth",
    "urllib3",
    "httpcore",
    "httpx",
    "anthropic",
    "langgraph",
    "langchain",
]


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_logging(
    log_level: str | None = None,
    log_dir: Path | None = None,
    app_name: str = "mail_classifier",
) -> None:
    """
    Configures structlog for the entire application.

    Args:
        log_level : Override log level. Falls back to LOG_LEVEL env var,
                    then DEBUG in development and INFO in production.
        log_dir   : Directory for log files. Defaults to <project_root>/logs.
        app_name  : Log file prefix. Defaults to "mail_classifier".

    Call once at startup — all loggers across the app inherit this config.
    """

    # --- Resolve environment and log level ---
    env = os.getenv("ENV", "development").lower()
    is_dev = env == "development"

    if log_level is None:
        log_level = os.getenv("LOG_LEVEL")
    if log_level is None:
        log_level = "DEBUG" if is_dev else "INFO"

    numeric_level = getattr(logging, log_level.upper(), logging.DEBUG)

    # --- Ensure log directory exists ---
    resolved_log_dir = log_dir or LOG_DIR
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = resolved_log_dir / f"{app_name}.log"

    # --- Shared processors ---
    # These run on every log call regardless of environment.
    # They enrich and normalise the event dict before rendering.
    shared_processors = [
        # Adds the logger name (module path) to every event
        structlog.stdlib.add_logger_name,
        # Adds the log level string to every event
        structlog.stdlib.add_log_level,
        # Adds a timestamp in ISO 8601 format
        structlog.processors.TimeStamper(fmt="iso"),
        # Extracts info from exceptions and adds it as structured fields
        structlog.processors.ExceptionRenderer(),
        # Renders positional args in log calls (e.g. logger.info("x=%s", val))
        structlog.stdlib.PositionalArgumentsFormatter(),
        # Converts any non-serialisable values to strings
        structlog.processors.UnicodeDecoder(),
    ]

    # --- Configure structlog ---
    structlog.configure(
        processors=shared_processors + [
            # Bridge to stdlib — lets structlog and stdlib logging work together.
            # Third-party libs that use stdlib logging will still be captured.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        # Use stdlib's logger factory so structlog plays nicely with
        # third-party libs that use logging.getLogger() directly.
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Cache the logger on first use — avoids repeated factory lookups
        cache_logger_on_first_use=True,
    )

    # --- Console renderer ---
    # Dev: human-readable coloured output. Prod: JSON (for log aggregators).
    if is_dev:
        console_renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        console_renderer = structlog.processors.JSONRenderer()

    # --- Build the stdlib ProcessorFormatter ---
    # This is the bridge that lets structlog output go through stdlib handlers
    # (StreamHandler, TimedRotatingFileHandler etc.)
    formatter_console = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    formatter_file = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # File always uses JSON — easy to parse with any log tool
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    # --- Handlers ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter_console)
    console_handler.setLevel(numeric_level)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",       # Rotate daily at midnight
        interval=1,
        backupCount=30,        # Keep 30 days of history
        encoding="utf-8",
        delay=True,            # Don't create file until first log message
    )
    file_handler.setFormatter(formatter_file)
    file_handler.setLevel(logging.DEBUG)  # File captures everything

    # --- Root logger ---
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()          # Remove any default handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # --- Silence noisy third-party loggers ---
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Confirm setup
    logger = structlog.get_logger(__name__)
    logger.info(
        "logging_configured",
        env=env,
        level=log_level.upper(),
        log_file=str(log_file),
        console_format="ConsoleRenderer" if is_dev else "JSON",
    )