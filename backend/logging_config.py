"""Structured logging compatibility helpers for Stash."""

from __future__ import annotations

import logging
import os
from typing import Any


class _FallbackLogger:
    """Small logger wrapper used only when structlog is not installed locally."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _message(self, event: str, kwargs: dict[str, Any]) -> str:
        if not kwargs:
            return event
        return f"{event} {kwargs}"

    def debug(self, event: str, **kwargs: Any) -> None:
        """Log a debug event."""
        self._logger.debug(self._message(event, kwargs))

    def info(self, event: str, **kwargs: Any) -> None:
        """Log an info event."""
        self._logger.info(self._message(event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        """Log a warning event."""
        self._logger.warning(self._message(event, kwargs))

    def error(self, event: str, **kwargs: Any) -> None:
        """Log an error event."""
        self._logger.error(self._message(event, kwargs))

    def exception(self, event: str, **kwargs: Any) -> None:
        """Log an exception event."""
        self._logger.exception(self._message(event, kwargs))


class _FallbackProcessors:
    """No-op processor namespace matching the structlog attributes used by Stash."""

    class TimeStamper:
        """No-op timestamp processor."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class StackInfoRenderer:
        """No-op stack info processor."""

        def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

    @staticmethod
    def format_exc_info(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """No-op exception formatter."""
        return {}

    class JSONRenderer:
        """No-op JSON renderer."""

        def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}


class _FallbackStdlib:
    """No-op stdlib processor namespace."""

    @staticmethod
    def add_log_level(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """No-op log-level processor."""
        return {}


class _FallbackStructlog:
    """Minimal structlog-shaped fallback for local test environments."""

    BoundLogger = _FallbackLogger
    processors = _FallbackProcessors()
    stdlib = _FallbackStdlib()

    @staticmethod
    def configure(*args: Any, **kwargs: Any) -> None:
        """Accept structlog.configure calls without side effects."""
        logging.basicConfig(level=logging.INFO)

    @staticmethod
    def get_logger(name: str) -> _FallbackLogger:
        """Return a fallback structured logger."""
        return _FallbackLogger(name)


try:
    import structlog as structlog
except ModuleNotFoundError:
    structlog = _FallbackStructlog()


def disable_dead_local_proxy() -> None:
    """Remove dead local proxy variables that break outbound API calls on Windows."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        value = os.environ.get(name, "")
        if value.startswith("http://127.0.0.1:9") or value.startswith("https://127.0.0.1:9"):
            os.environ.pop(name, None)


disable_dead_local_proxy()
