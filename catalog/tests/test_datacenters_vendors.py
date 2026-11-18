"""Tests for /api/v1/datacenters and /api/v1/vendors.

Both resources are public for reading and admin-only for writing. A
datacenter / vendor that still has instances cannot be deleted (409).
"""

import pytest
from django.urls import reverse
from rest_framework import status

from catalog.models import Datacenter, HardwareVendor
from catalog.views import SERVER_FORMS, plural_uk

pytestmark = pytest.mark.django_db


@pytest.fixture
def datacenter_payload():
    return {
        "name": "europe-central2-a",
        "region_code": "europe-central2",
        "city": "Warsaw",
        "country": "Poland",
        "sla_percent": "99.95",
    }


@pytest.fixture
def vendor_payload():
    return {
        "name": "Google TPU",
        "architecture": "TPU v5e",
        "website": "https://cloud.google.com/tpu",
    }


class TestDatacenters:
    list_url = reverse("catalog:datacenter-list")

    @staticmethod
    def detail_url(pk):
        return reverse("catalog:datacenter-detail", args=[pk])

    def test_anyone_can_list_and_read(self, api_client, datacenter):
        list_response = api_client.get(self.list_url)
        detail_response = api_client.get(self.detail_url(datacenter.id))

        assert list_response.status_code == status.HTTP_200_OK
        assert [dc["name"] for dc in list_response.json()] == [datacenter.name]
        assert detail_response.json()["sla_percent"] == "99.99"

    def test_related_instances(self, api_client, datacenter, cpu_instance):
        url = reverse("catalog:datacenter-instances", args=[datacenter.id])

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert [item["id"] for item in response.json()] == [cpu_instance.id]

    def test_related_instances_of_unknown_datacenter(self, api_client, assert_error):
        url = reverse("catalog:datacenter-instances", args=[9999])

        assert_error(api_client.get(url), status.HTTP_404_NOT_FOUND, "not_found")

    def test_admin_creates_datacenter(self, admin_api_client, datacenter_payload):
        response = admin_api_client.post(
            self.list_url, datacenter_payload, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Datacenter.objects.filter(name="europe-central2-a").exists()

    def test_regular_user_cannot_create(
        self, user_api_client, datacenter_payload, assert_error
    ):
        response = user_api_client.post(
            self.list_url, datacenter_payload, format="json"
        )

        assert_error(response, status.HTTP_403_FORBIDDEN, "permission_denied")
        assert not Datacenter.objects.exists()

    def test_anonymous_cannot_create(
        self, api_client, datacenter_payload, assert_error
    ):
        response = api_client.post(self.list_url, datacenter_payload, format="json")

        assert_error(response, status.HTTP_401_UNAUTHORIZED, "not_authenticated")

    def test_sla_must_be_a_percentage(
        self, admin_api_client, datacenter_payload, assert_error
    ):
        datacenter_payload["sla_percent"] = "120"

        response = admin_api_client.post(
            self.list_url, datacenter_payload, format="json"
        )

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert "sla_percent" in error["details"]

    def test_admin_updates_datacenter(self, admin_api_client, datacenter):
        response = admin_api_client.patch(
            self.detail_url(datacenter.id), {"city": "Frankfurt am Main"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        datacenter.refresh_from_db()
        assert datacenter.city == "Frankfurt am Main"

    def test_admin_deletes_empty_datacenter(self, admin_api_client, empty_datacenter):
        response = admin_api_client.delete(self.detail_url(empty_datacenter.id))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Datacenter.objects.filter(pk=empty_datacenter.id).exists()

    def test_datacenter_with_instances_cannot_be_deleted(
        self, admin_api_client, datacenter, gpu_instance, cpu_instance, assert_error
    ):
        response = admin_api_client.delete(self.detail_url(datacenter.id))

        error = assert_error(
            response, status.HTTP_409_CONFLICT, "datacenter_has_instances"
        )
        assert error["details"] == {"instances_count": 2}
        assert "2 сервери" in error["message"]
        assert Datacenter.objects.filter(pk=datacenter.id).exists()


class TestVendors:
    list_url = reverse("catalog:vendor-list")

    @staticmethod
    def detail_url(pk):
        return reverse("catalog:vendor-detail", args=[pk])

    def test_admin_full_crud_cycle(self, admin_api_client, vendor_payload):
        created = admin_api_client.post(self.list_url, vendor_payload, format="json")
        assert created.status_code == status.HTTP_201_CREATED
        url = self.detail_url(created.json()["id"])

        updated = admin_api_client.put(
            url, {**vendor_payload, "architecture": "TPU v6e"}, format="json"
        )
        assert updated.status_code == status.HTTP_200_OK
        assert updated.json()["architecture"] == "TPU v6e"

        deleted = admin_api_client.delete(url)
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not HardwareVendor.objects.exists()

    def test_regular_user_cannot_delete(
        self, user_api_client, empty_vendor, assert_error
    ):
        response = user_api_client.delete(self.detail_url(empty_vendor.id))

        assert_error(response, status.HTTP_403_FORBIDDEN, "permission_denied")

    def test_vendor_with_instances_cannot_be_deleted(
        self, admin_api_client, vendor, cpu_instance, assert_error
    ):
        response = admin_api_client.delete(self.detail_url(vendor.id))

        error = assert_error(response, status.HTTP_409_CONFLICT, "vendor_has_instances")
        assert "1 сервер" in error["message"]

    def test_unknown_vendor_returns_404(self, api_client, assert_error):
        response = api_client.get(self.detail_url(9999))

        error = assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")
        assert "9999" in error["message"]

    def test_related_instances(self, api_client, vendor, gpu_instance):
        url = reverse("catalog:vendor-instances", args=[vendor.id])

        response = api_client.get(url)

        assert [item["name"] for item in response.json()] == [gpu_instance.name]

    def test_duplicate_vendor_name(
        self, admin_api_client, vendor, vendor_payload, assert_error
    ):
        vendor_payload["name"] = vendor.name

        response = admin_api_client.post(self.list_url, vendor_payload, format="json")

        error = assert_error(response, status.HTTP_400_BAD_REQUEST, "validation_error")
        assert "name" in error["details"]


def test_unknown_api_endpoint_returns_json_404(api_client, assert_error):
    response = api_client.get("/api/v1/instances/")

    error = assert_error(response, status.HTTP_404_NOT_FOUND, "not_found")
    assert "без кінцевого слеша" in error["message"]


def test_openapi_schema_and_docs_ui_are_served(api_client):
    root = api_client.get("/")
    assert root.status_code == status.HTTP_302_FOUND
    assert root["Location"] == "/api/docs"

    swagger = api_client.get("/api/docs")
    redoc = api_client.get("/api/redoc")
    schema_yaml = api_client.get("/api/schema")
    schema_json = api_client.get("/api/schema", {"format": "json"})

    assert swagger.status_code == status.HTTP_200_OK
    assert redoc.status_code == status.HTTP_200_OK
    assert schema_yaml.status_code == status.HTTP_200_OK
    assert schema_json.status_code == status.HTTP_200_OK
    data = schema_json.json()
    assert data["info"]["title"] == "SkyCompute API"
    assert "/api/v1/instances" in data["paths"]
    assert "/api/v1/instances/{id}" in data["paths"]


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 сервер"),
        (2, "2 сервери"),
        (5, "5 серверів"),
        (11, "11 серверів"),
        (21, "21 сервер"),
        (22, "22 сервери"),
        (25, "25 серверів"),
    ],
)
def test_plural_forms_in_conflict_messages(count, expected):
    assert plural_uk(count, SERVER_FORMS) == expected
