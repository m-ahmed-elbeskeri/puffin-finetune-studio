"""Custom exceptions raised throughout the puffin pipeline."""

from __future__ import annotations


class PuffinError(Exception):
    """Base for all puffin errors."""


class ConfigError(PuffinError):
    """Raised when a config file is invalid or missing required fields."""


class DataValidationError(PuffinError):
    """Raised when a dataset record fails schema or quality validation."""


class GateError(PuffinError):
    """Raised when an evaluation gate blocks model promotion."""


class GuardrailError(PuffinError):
    """Raised when a serving guardrail rejects a request or response."""


class ProviderNotAvailableError(PuffinError):
    """Raised when a provider SDK is not installed or configured."""
