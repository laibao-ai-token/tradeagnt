"""Provider registry primitives."""

from typing import Dict, Type

from .fetcher import BaseFetcher


class ProviderRegistry(object):
    """Register and resolve provider fetchers by provider/data type."""

    _fetchers = {}  # type: Dict[str, Dict[str, Type[BaseFetcher]]]

    @classmethod
    def register(cls, provider, data_type, fetcher_cls):
        """Register a fetcher class for a provider and data type."""

        if provider not in cls._fetchers:
            cls._fetchers[provider] = {}
        cls._fetchers[provider][data_type] = fetcher_cls

    @classmethod
    def get(cls, provider, data_type):
        """Return the registered fetcher class, if any."""

        return cls._fetchers.get(provider, {}).get(data_type)

    @classmethod
    def list_providers(cls):
        """Return registered provider names."""

        return list(cls._fetchers.keys())

    @classmethod
    def list_data_types(cls, provider):
        """Return registered data types for one provider."""

        return list(cls._fetchers.get(provider, {}).keys())


def register_fetcher(provider, data_type):
    """Decorator that registers a fetcher class in ProviderRegistry."""

    def decorator(fetcher_cls):
        fetcher_cls.provider = provider
        ProviderRegistry.register(provider, data_type, fetcher_cls)
        return fetcher_cls

    return decorator
