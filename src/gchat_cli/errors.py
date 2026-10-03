"""Error types and stable exit codes.

Every failure surfaces as a :class:`GchatError` so that the CLI can print a
single, machine-readable JSON error object and exit with a documented code.
"""

from __future__ import annotations

import json
from enum import IntEnum
from typing import Any

import requests


class ExitCode(IntEnum):
    """Process exit codes. These are part of the public interface."""

    OK = 0
    API = 1
    AUTH = 2
    VALIDATION = 3
    POLICY = 4
    INTERNAL = 5


class GchatError(Exception):
    """Base class for all expected errors."""

    exit_code: ExitCode = ExitCode.INTERNAL
    reason: str = "internal"

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if reason is not None:
            self.reason = reason
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "exitCode": int(self.exit_code),
            "reason": self.reason,
            "message": self.message,
        }
        if self.hint:
            error["hint"] = self.hint
        error.update(self.details)
        return {"error": error}


class ValidationError(GchatError):
    """Invalid user input (bad resource name, malformed JSON, ...)."""

    exit_code = ExitCode.VALIDATION
    reason = "invalidArgument"


class AuthError(GchatError):
    """Missing, expired or unusable credentials."""

    exit_code = ExitCode.AUTH
    reason = "unauthenticated"


class PolicyError(GchatError):
    """The local policy (allowlist, read-only mode, confirmation) refused the action."""

    exit_code = ExitCode.POLICY
    reason = "policyDenied"


class ConfirmationRequired(PolicyError):
    """A write was attempted non-interactively without ``--yes``."""

    reason = "confirmationRequired"


class NetworkError(GchatError):
    """The API could not be reached (DNS, TLS, timeout, connection reset)."""

    exit_code = ExitCode.API
    reason = "networkError"


class ApiError(GchatError):
    """The Google Chat API returned an error response."""

    exit_code = ExitCode.API
    reason = "apiError"

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        status: str | None = None,
        hint: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {"httpStatus": http_status}
        if status:
            merged["status"] = status
        merged.update(details or {})
        super().__init__(message, hint=hint, reason=reason, details=merged)
        self.http_status = http_status
        self.status = status

    @classmethod
    def from_response(cls, response: requests.Response) -> ApiError:
        """Build an error from a Google API JSON error payload."""
        status: str | None = None
        reason: str | None = None
        message = f"HTTP {response.status_code}"
        extra: dict[str, Any] = {}
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            err = payload["error"]
            message = str(err.get("message") or message)
            status = err.get("status")
            for detail in err.get("details") or []:
                if not isinstance(detail, dict):
                    continue
                if detail.get("reason"):
                    reason = str(detail["reason"])
                metadata = detail.get("metadata") or {}
                if isinstance(metadata, dict) and metadata.get("activationUrl"):
                    extra["enableUrl"] = metadata["activationUrl"]
        elif response.text:
            message = response.text.strip()[:500]
        hint = _hint_for(response.status_code, status, reason, message)
        return cls(
            message,
            http_status=response.status_code,
            status=status,
            reason=reason or (status or "apiError"),
            hint=hint,
            details=extra,
        )


def _hint_for(code: int, status: str | None, reason: str | None, message: str) -> str | None:
    lowered = message.lower()
    if code == 401:
        return "Credentials are invalid or expired. Run `gchat auth login`."
    if reason in {"SERVICE_DISABLED", "accessNotConfigured"} or "has not been used" in lowered:
        return "Enable the Google Chat API (and configure the Chat app) in your Cloud project."
    if code == 403 and (
        "insufficient authentication scopes" in lowered
        or reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT"
    ):
        return (
            "The token lacks a required scope. Re-run `gchat auth login --scopes full` "
            "(or a preset that includes the needed scope)."
        )
    if code == 403:
        return "Permission denied: check that you are a member of the space and allowed to act."
    if code == 404:
        return "Not found: check the resource name and that you are a member of the space."
    if code == 429:
        return "Rate limited by Google Chat. Wait and retry, or lower request volume."
    if status == "INVALID_ARGUMENT":
        return "The API rejected the request. Check filters, names and the request body."
    return None
