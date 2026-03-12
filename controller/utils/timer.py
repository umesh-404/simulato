"""
Execution timer utility.

Provides context-manager based timing for operations.
Used in logging and performance measurement.
"""

import time
from typing import Optional

from controller.utils.logger import get_logger

logger = get_logger("timer")


class ExecutionTimer:
    """
    Context manager that measures wall-clock elapsed time.

    Usage:
        with ExecutionTimer("grok_api_call") as t:
            result = call_grok(...)
        print(t.elapsed_ms)
    """

    def __init__(self, operation_name: str) -> None:
        self.operation_name = operation_name
        self._start: Optional[float] = None
        self._end: Optional[float] = None

    def __enter__(self) -> "ExecutionTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._end = time.perf_counter()
        logger.debug(
            "Timer [%s]: %.1f ms",
            self.operation_name,
            self.elapsed_ms,
        )
        return None

    @property
    def elapsed_ms(self) -> float:
        if self._start is None:
            return 0.0
        end = self._end if self._end is not None else time.perf_counter()
        return (end - self._start) * 1000.0
