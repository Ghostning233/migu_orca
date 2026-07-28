from __future__ import annotations

from typing import Any


class Stage1Error(Exception):
    """Expected Stage 1 failure that can be returned to the caller."""

    def __init__(
        self,
        error_type: str,
        message: str,
        failed_step: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.failed_step = failed_step
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "error_message": self.message,
            "failed_step": self.failed_step,
            "details": self.details,
        }
