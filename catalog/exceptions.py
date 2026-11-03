"""Unified error handling for the API.

Every error response has the same JSON shape::

    {
        "error": {
            "status": 409,
            "code": "conflict",
            "message": "Human readable explanation of what went wrong.",
            "details": {}
        }
    }

``details`` holds per-field validation messages for 400 responses and extra
context (e.g. the number of related objects) for business-rule conflicts.
"""

from django.db.models import ProtectedError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.views import exception_handler

VALIDATION_MESSAGE = (
    "Передані дані некоректні. Виправте помилки, наведені в полі details, "
    "і повторіть запит."
)


class ConflictError(exceptions.APIException):
    """The request is valid but conflicts with the current state of data."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Запит конфліктує з поточним станом ресурсу."
    default_code = "conflict"

    def __init__(self, detail=None, code=None, details=None):
        super().__init__(detail, code)
        self.details = details or {}


def _message_from_detail(detail):
    """Turn an ErrorDetail / list / dict into a single readable string."""
    if isinstance(detail, list):
        return " ".join(_message_from_detail(item) for item in detail)
    if isinstance(detail, dict):
        return " ".join(_message_from_detail(item) for item in detail.values())
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, ProtectedError):
        # Safety net in case a view did not check related objects itself.
        exc = ConflictError(
            "Неможливо видалити об'єкт, оскільки на нього посилаються інші записи."
        )

    response = exception_handler(exc, context)
    if response is None:
        # Unexpected server error: let Django handle it (500).
        return None

    if isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
        message = VALIDATION_MESSAGE
        details = exc.detail
        if not isinstance(details, dict):
            details = {"non_field_errors": details}
    else:
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else "error"
        message = _message_from_detail(exc.detail)
        details = getattr(exc, "details", {})

    response.data = {
        "error": {
            "status": response.status_code,
            "code": code,
            "message": message,
            "details": details,
        }
    }
    return response
