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

import logging

from django.db.models import ProtectedError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)

VALIDATION_MESSAGE = (
    "Передані дані некоректні. Виправте помилки, наведені в полі details, "
    "і повторіть запит."
)
NOT_AUTHENTICATED_MESSAGE = (
    "Для виконання цього запиту необхідна авторизація. "
    "Передайте дійсний токен у заголовку Authorization: Bearer <access_token>."
)
INVALID_TOKEN_MESSAGE = (
    "Токен доступу недійсний або термін його дії минув. "
    "Оновіть токен за допомогою refresh-токена або увійдіть в акаунт повторно."
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
    elif isinstance(exc, TokenError) and not isinstance(exc, InvalidToken):
        exc = InvalidToken(exc.args[0])

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
    elif isinstance(exc, InvalidToken):
        code = "token_not_valid"
        message = INVALID_TOKEN_MESSAGE
        details = {}
    elif isinstance(exc, exceptions.NotAuthenticated):
        code = "not_authenticated"
        message = NOT_AUTHENTICATED_MESSAGE
        details = {}
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
    _log_api_error(context.get("request"), response.status_code, code, details)
    return response


def _log_api_error(request, status_code, code, details):
    """Log a handled API error without request bodies, passwords or tokens."""
    if request is None or code == "authentication_failed":
        # Failed logins are logged by users.serializers with the username.
        return
    user = getattr(request, "user", None)
    who = f"user_id={user.pk}" if user and user.is_authenticated else "anonymous"
    endpoint = f"{request.method} {request.path}"

    if status_code in (401, 403):
        # Security relevant: repeated failures may mean token or access abuse.
        logger.warning(
            "Access denied (%s %s): %s by %s", status_code, code, endpoint, who
        )
    elif status_code == 400:
        # Field names only: the values may contain passwords or tokens.
        fields = sorted(details) if isinstance(details, dict) else []
        logger.info("Validation failed: %s by %s, fields=%s", endpoint, who, fields)
    else:
        logger.info("API error %s (%s): %s by %s", status_code, code, endpoint, who)
