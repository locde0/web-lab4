import logging

from drf_spectacular.utils import OpenApiExample, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog import schema

from .serializers import (
    LoginSerializer,
    RegisterSerializer,
    TokenRefreshRequestSerializer,
    UserProfileSerializer,
)

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = schema.error_response(
    "Невірне ім'я користувача або пароль.",
    OpenApiExample(
        "Невірні дані для входу",
        value={
            "error": {
                "status": 401,
                "code": "authentication_failed",
                "message": "Невірне ім'я користувача або пароль.",
                "details": {},
            }
        },
        response_only=True,
        status_codes=["401"],
    ),
)

INVALID_REFRESH = schema.error_response(
    "Refresh-токен недійсний або прострочений — потрібно увійти повторно.",
    OpenApiExample(
        "Недійсний refresh-токен",
        value={
            "error": {
                "status": 401,
                "code": "token_not_valid",
                "message": "Токен доступу недійсний або термін його дії минув. "
                "Оновіть токен за допомогою refresh-токена або увійдіть в "
                "акаунт повторно.",
                "details": {},
            }
        },
        response_only=True,
        status_codes=["401"],
    ),
)


class PublicAuthAPIView(APIView):
    """Base view for public auth endpoints (register, login, refresh).

    Disables header token authentication so stale tokens do not block login or
    refresh, while keeping the Bearer challenge header for 401 responses.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'


class RegisterView(PublicAuthAPIView):
    """Register a new user account."""

    @extend_schema(
        tags=["auth"],
        summary="Реєстрація",
        description=(
            "Створює акаунт з роллю `user`. `username`, `email`, `password` і "
            "`password_confirmation` обов'язкові; `first_name` і `last_name` — ні. "
            "Пароль: від 8 символів, хоча б одна літера та цифра, не "
            "загальновідомий; зберігається лише у вигляді хешу."
        ),
        request=RegisterSerializer,
        responses={201: UserProfileSerializer, 400: schema.VALIDATION_ERROR},
        examples=[
            OpenApiExample(
                "Новий користувач",
                value={
                    "username": "ml_engineer",
                    "first_name": "Олена",
                    "last_name": "",
                    "email": "olena@example.com",
                    "password": "StrongPass123!",
                    "password_confirmation": "StrongPass123!",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            UserProfileSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class LoginView(PublicAuthAPIView):
    """Authenticate a user and return JWT access + refresh tokens."""

    @extend_schema(
        tags=["auth"],
        summary="Логін (отримати JWT)",
        description=(
            "Повертає пару токенів: `access` (15 хв, передається в заголовку "
            "`Authorization: Bearer <access>`) і `refresh` (7 днів, для "
            "`POST /api/v1/auth/refresh`)."
        ),
        request=LoginSerializer,
        responses={
            200: inline_serializer(
                "LoginResponse",
                fields={
                    "access": serializers.CharField(),
                    "refresh": serializers.CharField(),
                    "user": UserProfileSerializer(),
                },
            ),
            400: schema.VALIDATION_ERROR,
            401: INVALID_CREDENTIALS,
        },
        examples=[
            OpenApiExample(
                "Демо-адміністратор",
                value={"username": "admin", "password": "AdminPass123!"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class TokenRefreshView(PublicAuthAPIView):
    """Exchange a valid refresh token for a new access token."""

    @extend_schema(
        tags=["auth"],
        summary="Оновити access-токен",
        description="Обмінює дійсний `refresh`-токен на новий `access`-токен.",
        request=TokenRefreshRequestSerializer,
        responses={
            200: inline_serializer(
                "TokenRefreshResponse", fields={"access": serializers.CharField()}
            ),
            400: schema.VALIDATION_ERROR,
            401: INVALID_REFRESH,
        },
    )
    def post(self, request):
        serializer = TokenRefreshRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    """Retrieve or partially update the authenticated user's profile."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["users"],
        summary="Мій профіль",
        responses={200: UserProfileSerializer, 401: schema.NOT_AUTHENTICATED},
    )
    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)

    @extend_schema(
        tags=["users"],
        summary="Редагувати профіль",
        description="Можна змінити `email`, `first_name` і `last_name`.",
        request=UserProfileSerializer,
        responses={
            200: UserProfileSerializer,
            400: schema.VALIDATION_ERROR,
            401: schema.NOT_AUTHENTICATED,
        },
    )
    def patch(self, request):
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            "Profile updated: user_id=%s fields=%s",
            request.user.pk,
            sorted(serializer.validated_data),
        )
        return Response(serializer.data)
