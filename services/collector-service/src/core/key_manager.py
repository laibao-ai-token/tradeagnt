"""API key rotation helpers for provider integrations."""

import logging
import os
import random
import time
from threading import Lock

logger = logging.getLogger(__name__)


class KeyState(object):
    """Runtime state for one API key."""

    def __init__(self, key):
        self.key = key
        self.requests = 0
        self.errors = 0
        self.last_used = 0.0
        self.cooldown_until = 0.0

    @property
    def is_available(self):
        return time.time() >= self.cooldown_until


class KeyManager(object):
    """Manage multiple provider API keys with simple load balancing."""

    def __init__(self, env_var, strategy="round_robin", cooldown_seconds=60):
        self.env_var = env_var
        self.strategy = strategy
        self.cooldown_seconds = cooldown_seconds
        self._lock = Lock()
        self._index = 0

        raw = os.getenv(env_var, "")
        keys = [item.strip() for item in raw.split(",") if item.strip()]
        self._keys = {key: KeyState(key) for key in keys}

        if keys:
            logger.info("[KeyManager] %s: loaded %d key(s)", env_var, len(keys))

    @property
    def available_keys(self):
        return [state for state in self._keys.values() if state.is_available]

    def get_key(self):
        """Return one key according to the configured strategy."""

        with self._lock:
            available = self.available_keys
            if not available:
                if self._keys:
                    return min(self._keys.values(), key=lambda state: state.cooldown_until).key
                return None

            if self.strategy == "round_robin":
                state = available[self._index % len(available)]
                self._index += 1
            elif self.strategy == "least_used":
                state = min(available, key=lambda item: item.requests)
            else:
                state = random.choice(available)

            state.requests += 1
            state.last_used = time.time()
            return state.key

    def report_success(self, key):
        """Reset transient error count after a successful request."""

        if key in self._keys:
            self._keys[key].errors = 0

    def report_error(self, key, cooldown=True):
        """Record an error and optionally put the key into cooldown."""

        if key not in self._keys:
            return

        state = self._keys[key]
        state.errors += 1
        if cooldown and state.errors >= 3:
            state.cooldown_until = time.time() + self.cooldown_seconds
            logger.warning("[KeyManager] %s... cooldown=%ss", key[:8], self.cooldown_seconds)

    def stats(self):
        """Return a redacted snapshot of current key usage."""

        return {
            "total": len(self._keys),
            "available": len(self.available_keys),
            "keys": [
                {
                    "key": "{0}...".format(state.key[:8]),
                    "requests": state.requests,
                    "errors": state.errors,
                    "available": state.is_available,
                }
                for state in self._keys.values()
            ],
        }


_managers = {}


def get_key_manager(env_var, **kwargs):
    """Return a cached KeyManager per env var name."""

    if env_var not in _managers:
        _managers[env_var] = KeyManager(env_var, **kwargs)
    return _managers[env_var]
