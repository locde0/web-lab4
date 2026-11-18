"""Tests for the /api/v1/instances resource.

The resource supports GET / POST / PUT / PATCH / DELETE and has different
rules per role:

* anonymous - read only (list, detail);
* user      - read, create and update;
* admin     - everything, including delete.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import AccessToken

from catalog.models import InstanceType

pytestmark = pytest.mark.django_db

LIST_URL = reverse("catalog:instance-list")


def detail_url(pk):
    return reverse("catalog:instance-detail", args=[pk])


# --- GET /instances --------------------------------------------------------------


class TestInstanceList:
    def test_anonymous_gets_paginated_catalog(
        self, api_client, gpu_instance, cpu_instance
    ):
        response = api_client.get(LIST_URL)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert body["limit"] == 10
        assert [item["name"] for item in body["results"]] == [
            gpu_instance.name,
            cpu_instance.name,
        ]

    def test_list_item_has_short_nested_relations(self, api_client, cpu_instance):
        item = api_client.get(LIST_URL).json()["results"][0]

        assert item["datacenter"] == {
            "id": cpu_instance.datacenter.id,
            "name": "europe-west3-a",
            "city": "Frankfurt",
        }
        assert item["vendor"] == {"id": cpu_instance.vendor.id, "name": "NVIDIA"}
        # Empty GPU model is shown as null, not as an empty string.
        assert item["gpu_model"] is None

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"search": "a100"}, ["a2-highgpu-1g"]),
            ({"search": "STANDARD"}, ["e2-standard-2"]),
            ({"category": "general"}, ["e2-standard-2"]),
            ({"sort": "price"}, ["e2-standard-2", "a2-highgpu-1g"]),
            ({"sort": "-ram_gb"}, ["a2-highgpu-1g", "e2-standard-2"]),
            ({"limit": 1, "page": 2}, ["e2-standard-2"]),
        ],
    )
    def test_search_filter_sort_and_pagination(
        self, api_client, gpu_instance, cpu_instance, params, expected
    ):
        response = api_client.get(LIST_URL, params)

        assert response.status_code == status.HTTP_200_OK
        assert [item["name"] for item in response.json()["results"]] == expected

    def test_filter_by_datacenter_and_vendor(
        self, api_client, cpu_instance, empty_datacenter, empty_vendor
    ):
        by_dc = api_client.get(LIST_URL, {"datacenter_id": empty_datacenter.id})
        by_vendor = api_client.get(LIST_URL, {"vendor_id": cpu_instance.vendor.id})

        assert by_dc.json()["total"] == 0
        assert by_vendor.json()["total"] == 1

    @pytest.mark.parametrize(
        ("params", "field"),
        [
            ({"category": "quantum"}, "category"),
            ({"sort": "name"}, "sort"),
            ({"page": "abc"}, "page"),
            ({"page": 0}, "page"),
            ({"limit": 101}, "limit"),
            ({"datacenter_id": -1}, "datacenter_id"),
        ],
    )
    def test_invalid_query_params_return_400(
        self, api_client, assert_error, params, field
    ):
        response = api_client.get(LIST_URL, params)

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert field in error["details"]


# --- GET /instances/{id} ------------------------------------------------------------


class TestInstanceDetail:
    def test_anonymous_gets_full_configuration(self, api_client, gpu_instance):
        response = api_client.get(detail_url(gpu_instance.id))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "a2-highgpu-1g"
        assert body["hourly_price"] == "3.67"
        assert body["storage_type"] == "NVMe SSD"
        assert body["datacenter"]["region_code"] == "europe-west3"
        assert body["vendor"]["architecture"] == "Ampere"

    def test_unknown_id_returns_404(self, api_client, assert_error):
        response = api_client.get(detail_url(9999))

        error = assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")
        assert "9999" in error["message"]


# --- POST /instances ---------------------------------------------------------------


class TestInstanceCreate:
    @pytest.mark.parametrize("role", ["user", "admin"])
    def test_authenticated_user_creates_instance(
        self, client_for_role, instance_payload, role
    ):
        response = client_for_role(role).post(LIST_URL, instance_payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["name"] == instance_payload["name"]
        assert body["gpu_model"] is None
        assert body["is_available"] is True
        assert InstanceType.objects.filter(pk=body["id"]).exists()

    def test_anonymous_cannot_create(self, api_client, instance_payload, assert_error):
        response = api_client.post(LIST_URL, instance_payload, format="json")

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "not_authenticated")
        assert not InstanceType.objects.exists()

    def test_expired_token_is_rejected(
        self, api_client, regular_user, instance_payload, assert_error
    ):
        token = AccessToken.for_user(regular_user)
        token.set_exp(lifetime=-timedelta(minutes=1))
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = api_client.post(LIST_URL, instance_payload, format="json")

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "token_not_valid")

    def test_malformed_token_is_rejected(
        self, api_client, instance_payload, assert_error
    ):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")

        response = api_client.post(LIST_URL, instance_payload, format="json")

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "token_not_valid")

    def test_missing_required_fields(self, user_api_client, assert_error):
        response = user_api_client.post(LIST_URL, {}, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        for field in ("name", "category", "vcpu", "ram_gb", "hourly_price"):
            assert field in error["details"]

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"vcpu": 0}, "vcpu"),
            ({"hourly_price": "0.00"}, "hourly_price"),
            ({"category": "quantum"}, "category"),
            ({"storage_type": "Floppy"}, "storage_type"),
            ({"datacenter_id": 9999}, "datacenter_id"),
            ({"vendor_id": 9999}, "vendor_id"),
        ],
    )
    def test_invalid_field_values(
        self, user_api_client, instance_payload, assert_error, overrides, field
    ):
        instance_payload.update(overrides)

        response = user_api_client.post(LIST_URL, instance_payload, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert field in error["details"]

    def test_duplicate_name_is_rejected(
        self, user_api_client, instance_payload, cpu_instance, assert_error
    ):
        instance_payload["name"] = cpu_instance.name

        response = user_api_client.post(LIST_URL, instance_payload, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert "name" in error["details"]

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            # GPU count without a model.
            ({"gpu_count": 2, "gpu_model": None}, "gpu_model"),
            # GPU model without a count.
            ({"gpu_count": 0, "gpu_model": "NVIDIA L4"}, "gpu_count"),
            # Accelerator-optimized instance must have a GPU.
            ({"category": "accelerator_optimized"}, "gpu_count"),
        ],
    )
    def test_gpu_business_rules(
        self, user_api_client, instance_payload, assert_error, overrides, field
    ):
        instance_payload.update(overrides)

        response = user_api_client.post(LIST_URL, instance_payload, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert field in error["details"]


# --- PUT / PATCH /instances/{id} -----------------------------------------------------


class TestInstanceUpdate:
    def test_user_replaces_instance_with_put(
        self, user_api_client, cpu_instance, instance_payload
    ):
        instance_payload["name"] = "e2-standard-4"
        instance_payload["vcpu"] = 4

        response = user_api_client.put(
            detail_url(cpu_instance.id), instance_payload, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        cpu_instance.refresh_from_db()
        assert cpu_instance.name == "e2-standard-4"
        assert cpu_instance.vcpu == 4

    def test_put_requires_all_fields(self, user_api_client, cpu_instance, assert_error):
        response = user_api_client.put(
            detail_url(cpu_instance.id), {"vcpu": 4}, format="json"
        )

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert "name" in error["details"]

    def test_admin_patches_only_given_fields(self, admin_api_client, cpu_instance):
        response = admin_api_client.patch(
            detail_url(cpu_instance.id),
            {"is_available": False, "hourly_price": "0.09"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        cpu_instance.refresh_from_db()
        assert cpu_instance.is_available is False
        assert str(cpu_instance.hourly_price) == "0.09"
        assert cpu_instance.name == "e2-standard-2"

    def test_patch_checks_rules_against_current_values(
        self, user_api_client, gpu_instance, assert_error
    ):
        # The instance is accelerator_optimized, so the GPU cannot be removed.
        response = user_api_client.patch(
            detail_url(gpu_instance.id),
            {"gpu_count": 0, "gpu_model": None},
            format="json",
        )

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert "gpu_count" in error["details"]

    def test_anonymous_cannot_update(self, api_client, cpu_instance, assert_error):
        response = api_client.patch(
            detail_url(cpu_instance.id), {"vcpu": 64}, format="json"
        )

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "not_authenticated")
        cpu_instance.refresh_from_db()
        assert cpu_instance.vcpu == 2

    def test_update_unknown_instance_returns_404(self, user_api_client, assert_error):
        response = user_api_client.patch(detail_url(9999), {"vcpu": 4}, format="json")

        assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")


# --- DELETE /instances/{id} ----------------------------------------------------------


class TestInstanceDelete:
    def test_admin_deletes_instance(self, admin_api_client, cpu_instance):
        response = admin_api_client.delete(detail_url(cpu_instance.id))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        assert not InstanceType.objects.filter(pk=cpu_instance.id).exists()

    def test_regular_user_gets_403(self, user_api_client, cpu_instance, assert_error):
        response = user_api_client.delete(detail_url(cpu_instance.id))

        assert_error(response, status.HTTP_403_FORBIDDEN, "permission_denied")
        assert InstanceType.objects.filter(pk=cpu_instance.id).exists()

    def test_anonymous_gets_401(self, api_client, cpu_instance, assert_error):
        response = api_client.delete(detail_url(cpu_instance.id))

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "not_authenticated")
        assert InstanceType.objects.filter(pk=cpu_instance.id).exists()

    def test_delete_unknown_instance_returns_404(self, admin_api_client, assert_error):
        response = admin_api_client.delete(detail_url(9999))

        assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")


# --- Permission matrix ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "method", "expected"),
    [
        ("anonymous", "get", status.HTTP_200_OK),
        ("anonymous", "patch", status.HTTP_401_UNAUTHORIZED),
        ("anonymous", "delete", status.HTTP_401_UNAUTHORIZED),
        ("user", "get", status.HTTP_200_OK),
        ("user", "patch", status.HTTP_200_OK),
        ("user", "delete", status.HTTP_403_FORBIDDEN),
        ("admin", "get", status.HTTP_200_OK),
        ("admin", "patch", status.HTTP_200_OK),
        ("admin", "delete", status.HTTP_204_NO_CONTENT),
    ],
)
def test_permission_matrix(client_for_role, cpu_instance, role, method, expected):
    request = getattr(client_for_role(role), method)
    kwargs = {"data": {"vcpu": 4}, "format": "json"} if method == "patch" else {}

    response = request(detail_url(cpu_instance.id), **kwargs)

    assert response.status_code == expected
