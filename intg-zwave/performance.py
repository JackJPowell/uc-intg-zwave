#!/usr/bin/env python3
"""
Performance monitoring and debugging utilities for Z-Wave integration.

This module provides tools to track function calls, measure execution times,
and identify potential performance bottlenecks.
"""

import asyncio
import functools
import logging
import time
from collections import defaultdict
from typing import Callable, Dict

_LOG = logging.getLogger("performance")

# Performance tracking
_call_counts: Dict[str, int] = defaultdict(int)
_call_times: Dict[str, list] = defaultdict(list)
_slow_calls: list = []


class PerformanceMonitor:
    """Monitor and track performance metrics."""

    def __init__(self):
        self.call_counts = defaultdict(int)
        self.call_times = defaultdict(list)
        self.slow_threshold_ms = 100  # Log calls slower than this
        self.enabled = True

    def reset(self):
        """Reset all metrics."""
        self.call_counts.clear()
        self.call_times.clear()
        _slow_calls.clear()

    def get_stats(self) -> str:
        """Get formatted performance statistics."""
        if not self.call_counts:
            return "No performance data collected"

        lines = ["\n" + "=" * 80]
        lines.append("PERFORMANCE STATISTICS")
        lines.append("=" * 80)

        # Sort by total time spent
        sorted_funcs = sorted(
            self.call_times.items(), key=lambda x: sum(x[1]), reverse=True
        )

        lines.append(
            "\nFunction                                          Calls    Total(ms)    Avg(ms)      Max(ms)"
        )
        lines.append("-" * 100)

        for func_name, times in sorted_funcs:
            count = self.call_counts[func_name]
            total = sum(times) * 1000  # Convert to ms
            avg = (total / count) if count > 0 else 0
            max_time = max(times) * 1000 if times else 0

            lines.append(
                f"{func_name:<50} {count:<8} {total:<12.2f} {avg:<12.2f} {max_time:<12.2f}"
            )

        # Show slow calls
        if _slow_calls:
            lines.append("\n" + "=" * 80)
            lines.append(f"SLOW CALLS (>{self.slow_threshold_ms}ms)")
            lines.append("=" * 80)
            for entry in _slow_calls[-20:]:  # Last 20 slow calls
                time_ms = entry["time"]
                func = entry["func"]
                timestamp = entry["timestamp"]
                lines.append(
                    f"  {time_ms:.2f}ms - {func} - {timestamp}"
                )

        lines.append("=" * 80 + "\n")
        return "\n".join(lines)


# Global monitor instance
monitor = PerformanceMonitor()


def track_performance(func: Callable) -> Callable:
    """
    Decorator to track function performance.

    Tracks call count, execution time, and logs slow calls.
    Works with both sync and async functions.
    """
    func_name = f"{func.__module__}.{func.__name__}"

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not monitor.enabled:
                return await func(*args, **kwargs)

            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                monitor.call_counts[func_name] += 1
                monitor.call_times[func_name].append(elapsed)

                elapsed_ms = elapsed * 1000
                if elapsed_ms > monitor.slow_threshold_ms:
                    _slow_calls.append(
                        {
                            "func": func_name,
                            "time": elapsed_ms,
                            "timestamp": time.strftime("%H:%M:%S"),
                        }
                    )
                    _LOG.warning(
                        "⚠️  SLOW CALL: %s took %.2fms (threshold: %dms)",
                        func_name,
                        elapsed_ms,
                        monitor.slow_threshold_ms,
                    )
                else:
                    _LOG.debug("✓ %s completed in %.2fms", func_name, elapsed_ms)

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not monitor.enabled:
                return func(*args, **kwargs)

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                monitor.call_counts[func_name] += 1
                monitor.call_times[func_name].append(elapsed)

                elapsed_ms = elapsed * 1000
                if elapsed_ms > monitor.slow_threshold_ms:
                    _slow_calls.append(
                        {
                            "func": func_name,
                            "time": elapsed_ms,
                            "timestamp": time.strftime("%H:%M:%S"),
                        }
                    )
                    _LOG.warning(
                        "⚠️  SLOW CALL: %s took %.2fms (threshold: %dms)",
                        func_name,
                        elapsed_ms,
                        monitor.slow_threshold_ms,
                    )

        return sync_wrapper


def log_call(prefix: str = "📞"):
    """
    Decorator to log function calls with custom prefix.

    Args:
        prefix: Emoji or text prefix for the log message
    """

    def decorator(func: Callable) -> Callable:
        func_name = f"{func.__module__}.{func.__name__}"

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                _LOG.debug("%s CALL: %s", prefix, func_name)
                result = await func(*args, **kwargs)
                _LOG.debug("%s DONE: %s", prefix, func_name)
                return result

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                _LOG.debug("%s CALL: %s", prefix, func_name)
                result = func(*args, **kwargs)
                _LOG.debug("%s DONE: %s", prefix, func_name)
                return result

            return sync_wrapper

    return decorator


class CallTracker:
    """Track if a function is being called multiple times."""

    def __init__(self, name: str, warn_after: int = 2):
        self.name = name
        self.warn_after = warn_after
        self.count = 0
        self.last_call = 0

    def __enter__(self):
        self.count += 1
        current = time.time()
        time_since_last = (
            current - self.last_call if self.last_call > 0 else float("inf")
        )

        if self.count > self.warn_after:
            _LOG.warning(
                "🔄 MULTIPLE CALLS: %s has been called %d times (%.2fs since last call)",
                self.name,
                self.count,
                time_since_last,
            )

        self.last_call = current
        return self

    def __exit__(self, *args):
        pass

    def reset(self):
        """Reset the call counter."""
        self.count = 0
        self.last_call = 0


def print_performance_report():
    """Print a performance report to the log."""
    stats = monitor.get_stats()
    _LOG.info(stats)


def enable_performance_monitoring():
    """Enable performance monitoring."""
    monitor.enabled = True
    _LOG.info("🔍 Performance monitoring ENABLED")


def disable_performance_monitoring():
    """Disable performance monitoring."""
    monitor.enabled = False
    _LOG.info("Performance monitoring disabled")


def reset_performance_stats():
    """Reset all performance statistics."""
    monitor.reset()
    _LOG.info("Performance statistics reset")


def set_slow_call_threshold(threshold_ms: int):
    """Set the threshold for slow call warnings."""
    monitor.slow_threshold_ms = threshold_ms
    _LOG.info("Slow call threshold set to %dms", threshold_ms)
