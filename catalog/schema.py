"""Reusable building blocks for the OpenAPI documentation (drf-spectacular).

Every error in the API has the same JSON shape (see catalog.exceptions), so
error responses and their examples are declared once here and reused by the
views of both apps.
"""

from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from rest_framework import serializers


class ErrorBodySerializer(serializers.Serializer):
    status = serializers.IntegerField(help_text="HTTP-статус відповіді.")
    code = serializers.CharField(
        help_text="Машинний код помилки (validation_error, not_found, ...)."
    )
    message = serializers.CharField(help_text="Зрозуміле пояснення для людини.")
    details = serializers.DictField(
        help_text="Помилки по полях (400) або додатковий контекст (409).",
    )


class ErrorResponseSerializer(serializers.Serializer):
    """Common error envelope: {"error": {status, code, message, details}}."""

    error = ErrorBodySerializer()


def _error_example(name, status, code, message, details=None):
    return OpenApiExample(
        name,
        value={
            "error": {
                "status": status,
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
        response_only=True,
        status_codes=[str(status)],
    )


def error_response(description, *examples):
    return OpenApiResponse(
        response=ErrorResponseSerializer,
        description=description,
        examples=list(examples),
    )


VALIDATION_ERROR = error_response(
    "Передані дані некоректні; помилки по кожному полю — у `details`.",
    _error_example(
        "Помилка валідації",
        400,
        "validation_error",
        "Передані дані некоректні. Виправте помилки, наведені в полі details, "
        "і повторіть запит.",
        {"vcpu": ["Переконайтеся, що це значення більше або дорівнює 1."]},
    ),
)

NOT_AUTHENTICATED = error_response(
    "Токен не передано, або він недійсний / прострочений.",
    _error_example(
        "Немає токена",
        401,
        "not_authenticated",
        "Для виконання цього запиту необхідна авторизація. Передайте дійсний "
        "токен у заголовку Authorization: Bearer <access_token>.",
    ),
)

ADMIN_ONLY = error_response(
    "Користувач авторизований, але не має ролі `admin`.",
    _error_example(
        "Недостатньо прав",
        403,
        "permission_denied",
        "У вас недостатньо прав для виконання цієї дії. Ця операція доступна "
        "лише адміністраторам платформи.",
    ),
)


def not_found(message):
    return error_response(
        "Об'єкт із вказаним id не існує.",
        _error_example("Не знайдено", 404, "not_found", message),
    )


def conflict(code, message, count=1):
    return error_response(
        "Об'єкт не можна видалити, поки з ним пов'язані сервери.",
        _error_example(
            "Є пов'язані сервери",
            409,
            code,
            message,
            {"instances_count": count},
        ),
    )
