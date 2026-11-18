"""Shared pytest fixtures: API clients, users with different roles and catalog data.

Every test runs in its own transaction (pytest-django ``db`` fixture), so the
objects created here never leak between tests.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from catalog.models import Datacenter, HardwareVendor, InstanceType

User = get_user_model()

USER_PASSWORD = "UserPass123!"
ADMIN_PASSWORD = "AdminPass123!"


# --- Test environment ------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """PBKDF2 is slow on purpose; tests do not need a strong hash."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


# --- Users and authenticated clients -------------------------------------------


@pytest.fixture
def api_client():
    """Anonymous client without an Authorization header."""
    return APIClient()


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="developer",
        email="dev@example.com",
        password=USER_PASSWORD,
        first_name="Тарас",
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="admin",
        email="admin@example.com",
        password=ADMIN_PASSWORD,
        is_staff=True,
    )


def _client_for(user):
    """Client that sends a real JWT access token, like the frontend does."""
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def user_api_client(regular_user):
    return _client_for(regular_user)


@pytest.fixture
def admin_api_client(staff_user):
    return _client_for(staff_user)


@pytest.fixture
def client_for_role(api_client, user_api_client, admin_api_client):
    """Pick a client by role name; handy for parametrized permission tests."""
    clients = {
        "anonymous": api_client,
        "user": user_api_client,
        "admin": admin_api_client,
    }
    return clients.__getitem__


# --- Catalog data ----------------------------------------------------------------


@pytest.fixture
def datacenter(db):
    return Datacenter.objects.create(
        name="europe-west3-a",
        region_code="europe-west3",
        city="Frankfurt",
        country="Germany",
    )


@pytest.fixture
def empty_datacenter(db):
    """Datacenter without instances: can be deleted."""
    return Datacenter.objects.create(
        name="asia-northeast1-a",
        region_code="asia-northeast1",
        city="Tokyo",
        country="Japan",
    )


@pytest.fixture
def vendor(db):
    return HardwareVendor.objects.create(
        name="NVIDIA", architecture="Ampere", website="https://www.nvidia.com"
    )


@pytest.fixture
def empty_vendor(db):
    """Vendor without instances: can be deleted."""
    return HardwareVendor.objects.create(name="AMD", architecture="Instinct MI300X")


@pytest.fixture
def gpu_instance(datacenter, vendor):
    return InstanceType.objects.create(
        name="a2-highgpu-1g",
        category=InstanceType.Category.ACCELERATOR_OPTIMIZED,
        vcpu=12,
        ram_gb=85,
        gpu_model="NVIDIA A100 40GB",
        gpu_count=1,
        storage_type=InstanceType.StorageType.NVME_SSD,
        storage_size_gb=500,
        network_bandwidth_gbps=24,
        hourly_price=Decimal("3.67"),
        datacenter=datacenter,
        vendor=vendor,
    )


@pytest.fixture
def cpu_instance(datacenter, vendor):
    return InstanceType.objects.create(
        name="e2-standard-2",
        category=InstanceType.Category.GENERAL,
        vcpu=2,
        ram_gb=8,
        storage_type=InstanceType.StorageType.SSD,
        storage_size_gb=50,
        network_bandwidth_gbps=1,
        hourly_price=Decimal("0.07"),
        datacenter=datacenter,
        vendor=vendor,
    )


@pytest.fixture
def instance_payload(datacenter, vendor):
    """Valid body for POST / PUT /instances; override fields per test."""
    return {
        "name": "t2a-standard-4",
        "category": "general",
        "description": "ARM instance",
        "vcpu": 4,
        "ram_gb": 16,
        "gpu_model": None,
        "gpu_count": 0,
        "storage_type": "SSD",
        "storage_size_gb": 100,
        "network_bandwidth_gbps": 5,
        "hourly_price": "0.15",
        "datacenter_id": datacenter.id,
        "vendor_id": vendor.id,
    }


# --- Assertions ------------------------------------------------------------------


@pytest.fixture
def assert_error():
    """Check status code and the common {"error": {...}} envelope."""

    def check(response, status_code, code):
        assert response.status_code == status_code, response.content
        error = response.json()["error"]
        assert set(error) == {"status", "code", "message", "details"}
        assert error["status"] == status_code
        assert error["code"] == code
        assert error["message"]
        return error

    return check
