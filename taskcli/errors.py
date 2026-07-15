from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CliError(Exception):
    code: str
    message: str
    exit_code: int = 1
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class ConfigError(CliError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("config_error", message, 2, details or {})


class ValidationError(CliError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("validation_error", message, 2, details or {})


class AuthError(CliError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("auth_error", message, 3, details or {})


class NetworkError(CliError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("network_error", message, 4, details or {})


class RateLimitError(CliError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("rate_limited", message, 5, details or {})


class ProviderError(CliError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("provider_error", message, 6, details or {})

