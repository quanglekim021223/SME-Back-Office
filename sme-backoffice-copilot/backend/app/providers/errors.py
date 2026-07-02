"""Provider-specific exceptions for optional local adapters."""


class ProviderError(RuntimeError):
    """Base error raised by provider adapters."""


class ProviderConfigurationError(ProviderError):
    """Raised when provider inputs or settings are incomplete."""


class ProviderDependencyError(ProviderError):
    """Raised when an optional local provider dependency is unavailable."""


class ProviderExecutionError(ProviderError):
    """Raised when a provider call fails at runtime."""
