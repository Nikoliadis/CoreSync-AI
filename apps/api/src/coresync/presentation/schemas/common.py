"""Shared schema configuration.

camelCase on the wire, snake_case in Python. The alias generator handles the
translation in one place so neither side writes unnatural code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        # Unknown fields are rejected rather than ignored: a client sending `weightKG`
        # should get a clear 400, not a silently dropped value.
        extra="forbid",
        str_strip_whitespace=True,
    )


class ErrorDetail(ApiModel):
    field: str | None = None
    code: str
    message: str


class ErrorBody(ApiModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[ErrorDetail] = []


class ErrorResponse(ApiModel):
    error: ErrorBody

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "error": {
                    "code": "validation_error",
                    "message": "The request could not be validated.",
                    "requestId": "01H8X3K9P2Q4R5S6T7U8V9W0X1",
                    "details": [
                        {"field": "password", "code": "weak", "message": "Use 10+ characters."}
                    ],
                }
            }
        },
    )


class MessageResponse(ApiModel):
    message: str


class PaginationMeta(ApiModel):
    next_cursor: str | None = None
    previous_cursor: str | None = None
    has_more: bool = False
    limit: int = 25


class Page(ApiModel):
    data: list[Any]
    pagination: PaginationMeta
