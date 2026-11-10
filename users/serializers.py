from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    """Public representation of a user account and editable profile fields."""

    role = serializers.SerializerMethodField()
    email = serializers.EmailField(required=True, max_length=254)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_staff",
            "date_joined",
        ]
        read_only_fields = ["id", "username", "role", "is_staff", "date_joined"]

    def get_role(self, obj):
        return "admin" if obj.is_staff else "user"

    def validate_email(self, value):
        normalized = value.strip().lower()
        qs = User.objects.filter(email__iexact=normalized)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Користувач із такою електронною поштою вже зареєстрований."
            )
        return normalized


class RegisterSerializer(serializers.Serializer):
    """Validates registration input and creates a user with a hashed password."""

    username = serializers.CharField(
        required=True,
        max_length=150,
        validators=[UnicodeUsernameValidator()],
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        default="",
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        default="",
    )
    email = serializers.EmailField(
        required=True,
        max_length=254,
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        min_length=8,
        max_length=128,
        trim_whitespace=False,
    )
    password_confirmation = serializers.CharField(
        required=True,
        write_only=True,
        min_length=8,
        max_length=128,
        trim_whitespace=False,
    )

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Користувач із таким ім'ям вже існує.")
        return value

    def validate_email(self, value):
        normalized = value.strip().lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError(
                "Користувач із такою електронною поштою вже зареєстрований."
            )
        return normalized

    def validate(self, attrs):
        password = attrs.get("password", "")
        confirmation = attrs.get("password_confirmation", "")
        errors = {}

        if password != confirmation:
            errors["password_confirmation"] = ["Паролі не збігаються."]

        temp_user = User(
            username=attrs.get("username", ""),
            email=attrs.get("email", ""),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        password_errors = []
        try:
            validate_password(password, user=temp_user)
        except DjangoValidationError as exc:
            password_errors.extend(exc.messages)

        if not (
            any(ch.isalpha() for ch in password)
            and any(ch.isdigit() for ch in password)
        ):
            password_errors.append(
                "Пароль має містити щонайменше одну літеру та одну цифру."
            )

        if password_errors:
            errors["password"] = password_errors

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirmation", None)
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    """Authenticates a user and issues JWT access and refresh tokens."""

    username = serializers.CharField(required=True, max_length=150)
    password = serializers.CharField(
        required=True,
        write_only=True,
        max_length=128,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["username"],
            password=attrs["password"],
        )
        if user is None or not user.is_active:
            raise AuthenticationFailed("Невірне ім'я користувача або пароль.")

        refresh = RefreshToken.for_user(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserProfileSerializer(user).data,
        }


class TokenRefreshRequestSerializer(serializers.Serializer):
    """Validates a refresh token and issues a new access token."""

    refresh = serializers.CharField(required=True, max_length=2048)

    def validate(self, attrs):
        try:
            refresh = RefreshToken(attrs["refresh"])
        except TokenError as exc:
            raise InvalidToken(str(exc)) from exc

        return {"access": str(refresh.access_token)}
