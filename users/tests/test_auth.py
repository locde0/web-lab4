"""Tests for registration, JWT login / refresh and the current user profile."""

import logging
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from conftest import USER_PASSWORD

pytestmark = pytest.mark.django_db

User = get_user_model()

REGISTER_URL = reverse("users:register")
LOGIN_URL = reverse("users:login")
REFRESH_URL = reverse("users:token-refresh")
ME_URL = reverse("users:current-user")
INSTANCES_URL = reverse("catalog:instance-list")


@pytest.fixture
def registration_payload():
    return {
        "username": "ml_engineer",
        "first_name": "Олена",
        "last_name": "",
        "email": "Olena@Example.com",
        "password": "StrongPass123!",
        "password_confirmation": "StrongPass123!",
    }


class TestRegister:
    def test_creates_user_with_hashed_password(self, api_client, registration_payload):
        response = api_client.post(REGISTER_URL, registration_payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["username"] == "ml_engineer"
        assert body["email"] == "olena@example.com"  # normalized
        assert body["role"] == "user"
        assert "password" not in body

        user = User.objects.get(username="ml_engineer")
        assert user.password != "StrongPass123!"
        assert user.check_password("StrongPass123!")
        assert user.is_staff is False

    def test_names_are_optional(self, api_client, registration_payload):
        del registration_payload["first_name"]
        del registration_payload["last_name"]

        response = api_client.post(REGISTER_URL, registration_payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED

    def test_required_fields(self, api_client, assert_error):
        response = api_client.post(REGISTER_URL, {}, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert set(error["details"]) == {
            "username",
            "email",
            "password",
            "password_confirmation",
        }

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"email": "not-an-email"}, "email"),
            ({"username": "u" * 151}, "username"),
            ({"first_name": "x" * 151}, "first_name"),
            ({"password": "Ab1", "password_confirmation": "Ab1"}, "password"),
            (
                {"password": "onlyletters!", "password_confirmation": "onlyletters!"},
                "password",
            ),
            ({"password_confirmation": "OtherPass123!"}, "password_confirmation"),
        ],
    )
    def test_invalid_data(
        self, api_client, registration_payload, assert_error, overrides, field
    ):
        registration_payload.update(overrides)

        response = api_client.post(REGISTER_URL, registration_payload, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert field in error["details"]
        assert not User.objects.filter(username="ml_engineer").exists()

    @pytest.mark.parametrize(
        ("field", "value"),
        [("username", "DEVELOPER"), ("email", "DEV@example.com")],
    )
    def test_username_and_email_must_be_unique(
        self, api_client, regular_user, registration_payload, assert_error, field, value
    ):
        registration_payload[field] = value

        response = api_client.post(REGISTER_URL, registration_payload, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert field in error["details"]


class TestLoginAndRefresh:
    def test_login_returns_token_pair_and_user(self, api_client, regular_user):
        response = api_client.post(
            LOGIN_URL,
            {"username": "developer", "password": USER_PASSWORD},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["access"] and body["refresh"]
        assert body["user"]["role"] == "user"

    def test_access_token_opens_protected_endpoint(self, api_client, regular_user):
        tokens = api_client.post(
            LOGIN_URL,
            {"username": "developer", "password": USER_PASSWORD},
            format="json",
        ).json()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        response = api_client.get(ME_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["username"] == "developer"

    def test_wrong_password(self, api_client, regular_user, assert_error):
        response = api_client.post(
            LOGIN_URL, {"username": "developer", "password": "wrong"}, format="json"
        )

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "authentication_failed")

    def test_inactive_user_cannot_login(self, api_client, regular_user, assert_error):
        regular_user.is_active = False
        regular_user.save()

        response = api_client.post(
            LOGIN_URL,
            {"username": "developer", "password": USER_PASSWORD},
            format="json",
        )

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "authentication_failed")

    def test_login_requires_fields(self, api_client, assert_error):
        response = api_client.post(LOGIN_URL, {}, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert set(error["details"]) == {"username", "password"}

    def test_refresh_returns_new_access_token(self, api_client, regular_user):
        refresh = RefreshToken.for_user(regular_user)

        response = api_client.post(
            REFRESH_URL, {"refresh": str(refresh)}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        assert api_client.get(ME_URL).status_code == status.HTTP_200_OK

    @pytest.mark.parametrize("token_kind", ["garbage", "expired", "access"])
    def test_invalid_refresh_token(
        self, api_client, regular_user, assert_error, token_kind
    ):
        refresh = RefreshToken.for_user(regular_user)
        if token_kind == "expired":
            refresh.set_exp(lifetime=-timedelta(seconds=1))
        tokens = {
            "garbage": "not-a-jwt",
            "expired": str(refresh),
            # An access token must not be accepted as a refresh token.
            "access": str(refresh.access_token),
        }

        response = api_client.post(
            REFRESH_URL, {"refresh": tokens[token_kind]}, format="json"
        )

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "token_not_valid")

    def test_stale_header_does_not_block_login(self, api_client, regular_user):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer expired.or.broken")

        response = api_client.post(
            LOGIN_URL,
            {"username": "developer", "password": USER_PASSWORD},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK


class TestCurrentUser:
    def test_requires_authentication(self, api_client, assert_error):
        response = api_client.get(ME_URL)

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "not_authenticated")
        assert response["WWW-Authenticate"].startswith("Bearer")

    def test_admin_role_in_profile(self, admin_api_client):
        body = admin_api_client.get(ME_URL).json()

        assert body["role"] == "admin"
        assert body["is_staff"] is True

    def test_patch_updates_profile(self, user_api_client, regular_user):
        response = user_api_client.patch(
            ME_URL, {"last_name": "Шевченко", "email": "NEW@example.com"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        regular_user.refresh_from_db()
        assert regular_user.last_name == "Шевченко"
        assert regular_user.email == "new@example.com"

    def test_read_only_fields_are_ignored(self, user_api_client, regular_user):
        user_api_client.patch(
            ME_URL, {"username": "hacker", "is_staff": True}, format="json"
        )

        regular_user.refresh_from_db()
        assert regular_user.username == "developer"
        assert regular_user.is_staff is False

    def test_email_taken_by_another_user(
        self, user_api_client, staff_user, assert_error
    ):
        response = user_api_client.patch(
            ME_URL, {"email": staff_user.email}, format="json"
        )

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert "email" in error["details"]


class TestLogging:
    def test_successful_flow_is_logged_without_secrets(
        self, api_client, regular_user, caplog
    ):
        caplog.set_level(logging.DEBUG)

        tokens = api_client.post(
            LOGIN_URL,
            {"username": "developer", "password": USER_PASSWORD},
            format="json",
        ).json()
        api_client.post(REFRESH_URL, {"refresh": tokens["refresh"]}, format="json")

        assert f"User logged in: user_id={regular_user.pk}" in caplog.text
        assert USER_PASSWORD not in caplog.text
        assert tokens["access"] not in caplog.text
        assert tokens["refresh"] not in caplog.text

    def test_failed_login_is_warning_without_password(
        self, api_client, regular_user, caplog
    ):
        api_client.post(
            LOGIN_URL,
            {"username": "developer", "password": "SecretGuess1!"},
            format="json",
        )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Failed login attempt" in r.getMessage() for r in warnings)
        assert "SecretGuess1!" not in caplog.text

    def test_registration_errors_log_field_names_only(
        self, api_client, registration_payload, caplog
    ):
        registration_payload["password_confirmation"] = "Mismatch123!"

        api_client.post(REGISTER_URL, registration_payload, format="json")

        assert "fields=['password_confirmation']" in caplog.text
        assert "Mismatch123!" not in caplog.text
        assert "StrongPass123!" not in caplog.text

    def test_forbidden_action_is_logged_as_warning(
        self, user_api_client, regular_user, caplog
    ):
        user_api_client.post(
            reverse("catalog:datacenter-list"), {"name": "x"}, format="json"
        )

        record = next(r for r in caplog.records if "Access denied" in r.getMessage())
        assert record.levelno == logging.WARNING
        assert f"user_id={regular_user.pk}" in record.getMessage()

    def test_created_instance_is_logged(
        self, user_api_client, instance_payload, caplog
    ):
        caplog.set_level(logging.INFO)

        user_api_client.post(INSTANCES_URL, instance_payload, format="json")

        assert "InstanceType created" in caplog.text
