"""Lightweight metrics collector used by collector-service runtime."""

from __future__ import absolute_import

import threading
import time


class Metrics(object):
    """Thread-safe counter registry with a minimal surface."""

    def __init__(self):
        self._values = {}
        self._lock = threading.Lock()

    def inc(self, name, value=1):
        with self._lock:
            self._values[name] = int(self._values.get(name, 0)) + int(value)

    def set(self, name, value):
        with self._lock:
            self._values[name] = value

    def to_dict(self):
        with self._lock:
            return dict(self._values)

    def __str__(self):
        values = self.to_dict()
        parts = []
        for key in sorted(values.keys()):
            value = values[key]
            if value:
                parts.append("{0}={1}".format(key, value))
        return " | ".join(parts)


metrics = Metrics()


class Timer(object):
    """Simple timer helper compatible with the source collectors."""

    def __init__(self, metric_name, metrics_client=None):
        self._metric_name = metric_name
        self._metrics = metrics_client or metrics
        self._started_at = 0.0

    def __enter__(self):
        self._started_at = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type
        del exc
        del tb
        duration = time.perf_counter() - self._started_at
        self._metrics.set(self._metric_name, duration)
        self._metrics.set(self._metric_name.replace("duration", "time"), time.time())
        return False
