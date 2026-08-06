from __future__ import annotations

from typing import Any


class APIException(Exception):
    """Expected API failure that can be returned as the shared JSON envelope."""

    def __init__(
        self,
        error_type: str = "api_error",
        error_message: str = "A server error occurred.",
        error_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_message)
        self.error_type = error_type
        self.error_message = error_message
        self.error_data = error_data
