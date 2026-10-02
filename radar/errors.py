"""Shared exceptions."""

SOURCE_ERROR_KINDS = ("auth", "blocked", "transient", "schema")


class SourceError(Exception):
    """Raised by a Source.fetch so the scheduler can back off correctly."""

    def __init__(self, message, kind="transient"):
        if kind not in SOURCE_ERROR_KINDS:
            raise ValueError(f"invalid SourceError kind {kind!r}; expected one of {SOURCE_ERROR_KINDS}")
        super().__init__(message)
        self.kind = kind


class ConfigError(ValueError):
    """Raised when settings or a config/*.yaml file is missing or invalid."""
