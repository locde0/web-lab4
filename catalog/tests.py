from rest_framework import status
from rest_framework.test import APITestCase

from .models import Datacenter, HardwareVendor, InstanceType


class CatalogTestCase(APITestCase):
    def setUp(self):
        self.dc = Datacenter.objects.create(
            name="europe-west3-a",
            region_code="europe-west3",
            city="Frankfurt",
            country="Germany",
        )
        self.empty_dc = Datacenter.objects.create(
            name="asia-northeast1-a",
            region_code="asia-northeast1",
            city="Tokyo",
            country="Japan",
        )
        self.vendor = HardwareVendor.objects.create(
            name="NVIDIA", architecture="Ampere", website="https://www.nvidia.com"
        )
        self.empty_vendor = HardwareVendor.objects.create(
            name="AMD", architecture="Instinct MI300X"
        )
        self.gpu = InstanceType.objects.create(
            name="a2-highgpu-1g",
            category="accelerator_optimized",
            vcpu=12,
            ram_gb=85,
            gpu_model="NVIDIA A100 40GB",
            gpu_count=1,
            storage_type="NVMe SSD",
            storage_size_gb=500,
            network_bandwidth_gbps=10,
            hourly_price="3.67",
            datacenter=self.dc,
            vendor=self.vendor,
        )
        self.cpu = InstanceType.objects.create(
            name="e2-standard-2",
            category="general",
            vcpu=2,
            ram_gb=8,
            storage_type="SSD",
            storage_size_gb=50,
            network_bandwidth_gbps=1,
            hourly_price="0.07",
            datacenter=self.dc,
            vendor=self.vendor,
        )

    def instance_payload(self, **overrides):
        payload = {
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
            "datacenter_id": self.dc.id,
            "vendor_id": self.vendor.id,
        }
        payload.update(overrides)
        return payload

    def assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        error = response.json()["error"]
        self.assertEqual(set(error), {"status", "code", "message", "details"})
        self.assertEqual(error["status"], status_code)
        self.assertEqual(error["code"], code)
        self.assertTrue(error["message"])
        return error


class InstanceApiTests(CatalogTestCase):
    def test_list_is_paginated(self):
        response = self.client.get("/api/v1/instances", {"limit": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["limit"], 1)
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["datacenter"]["city"], "Frankfurt")

    def test_list_filters_search_and_sort(self):
        response = self.client.get("/api/v1/instances", {"sort": "price"})
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["e2-standard-2", "a2-highgpu-1g"])

        response = self.client.get("/api/v1/instances", {"search": "a100"})
        self.assertEqual(response.json()["total"], 1)

        response = self.client.get("/api/v1/instances", {"category": "general"})
        self.assertEqual(response.json()["results"][0]["gpu_model"], None)

    def test_list_rejects_invalid_query_params(self):
        response = self.client.get(
            "/api/v1/instances", {"sort": "name", "page": "abc", "limit": 500}
        )
        error = self.assert_error(response, 400, "validation_error")
        self.assertEqual(set(error["details"]), {"sort", "page", "limit"})

    def test_retrieve_returns_nested_relations(self):
        response = self.client.get(f"/api/v1/instances/{self.gpu.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["vendor"]["architecture"], "Ampere")

    def test_retrieve_missing_returns_404(self):
        self.assert_error(self.client.get("/api/v1/instances/999"), 404, "not_found")

    def test_create(self):
        response = self.client.post(
            "/api/v1/instances", self.instance_payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["datacenter_id"], self.dc.id)
        self.assertIsNone(body["gpu_model"])
        self.assertTrue(body["is_available"])
        self.assertTrue(InstanceType.objects.filter(name="t2a-standard-4").exists())

    def test_create_with_invalid_data_returns_400(self):
        response = self.client.post(
            "/api/v1/instances",
            self.instance_payload(vcpu=0, datacenter_id=999, name=self.gpu.name),
            format="json",
        )
        error = self.assert_error(response, 400, "validation_error")
        self.assertIn("vcpu", error["details"])
        self.assertIn("datacenter_id", error["details"])
        self.assertIn("name", error["details"])

    def test_accelerator_instance_requires_gpu(self):
        response = self.client.post(
            "/api/v1/instances",
            self.instance_payload(category="accelerator_optimized"),
            format="json",
        )
        error = self.assert_error(response, 400, "validation_error")
        self.assertIn("gpu_count", error["details"])

    def test_gpu_count_requires_gpu_model(self):
        response = self.client.post(
            "/api/v1/instances", self.instance_payload(gpu_count=2), format="json"
        )
        error = self.assert_error(response, 400, "validation_error")
        self.assertIn("gpu_model", error["details"])

    def test_put_replaces_instance(self):
        payload = self.instance_payload(name="e2-standard-4", vcpu=4)
        response = self.client.put(
            f"/api/v1/instances/{self.cpu.id}", payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cpu.refresh_from_db()
        self.assertEqual(self.cpu.name, "e2-standard-4")

    def test_put_requires_all_fields(self):
        response = self.client.put(
            f"/api/v1/instances/{self.cpu.id}", {"vcpu": 4}, format="json"
        )
        self.assert_error(response, 400, "validation_error")

    def test_patch_updates_single_field(self):
        response = self.client.patch(
            f"/api/v1/instances/{self.cpu.id}",
            {"is_available": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cpu.refresh_from_db()
        self.assertFalse(self.cpu.is_available)

    def test_patch_validates_against_current_values(self):
        # Removing the GPU from an accelerator instance is not allowed.
        response = self.client.patch(
            f"/api/v1/instances/{self.gpu.id}",
            {"gpu_model": None, "gpu_count": 0},
            format="json",
        )
        self.assert_error(response, 400, "validation_error")

    def test_delete(self):
        response = self.client.delete(f"/api/v1/instances/{self.cpu.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(InstanceType.objects.filter(id=self.cpu.id).exists())

    def test_delete_missing_returns_404(self):
        self.assert_error(self.client.delete("/api/v1/instances/999"), 404, "not_found")


class DatacenterApiTests(CatalogTestCase):
    def test_list(self):
        response = self.client.get("/api/v1/datacenters")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 2)

    def test_create_and_validate(self):
        payload = {
            "name": "europe-central2-a",
            "region_code": "europe-central2",
            "city": "Warsaw",
            "country": "Poland",
            "sla_percent": "99.99",
        }
        response = self.client.post("/api/v1/datacenters", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        payload["sla_percent"] = "150"
        response = self.client.post("/api/v1/datacenters", payload, format="json")
        error = self.assert_error(response, 400, "validation_error")
        self.assertEqual(set(error["details"]), {"name", "sla_percent"})

    def test_update(self):
        response = self.client.patch(
            f"/api/v1/datacenters/{self.dc.id}", {"city": "Berlin"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["city"], "Berlin")

    def test_instances_of_datacenter(self):
        response = self.client.get(f"/api/v1/datacenters/{self.dc.id}/instances")
        self.assertEqual(len(response.json()), 2)
        self.assert_error(
            self.client.get("/api/v1/datacenters/999/instances"), 404, "not_found"
        )

    def test_delete_empty_datacenter(self):
        response = self.client.delete(f"/api/v1/datacenters/{self.empty_dc.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_datacenter_with_instances_returns_409(self):
        response = self.client.delete(f"/api/v1/datacenters/{self.dc.id}")
        error = self.assert_error(response, 409, "datacenter_has_instances")
        self.assertEqual(error["details"], {"instances_count": 2})
        self.assertIn("2 сервери", error["message"])
        self.assertTrue(Datacenter.objects.filter(id=self.dc.id).exists())


class VendorApiTests(CatalogTestCase):
    def test_crud(self):
        response = self.client.post(
            "/api/v1/vendors",
            {"name": "Google Cloud TPU", "architecture": "TPU v4"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        vendor_id = response.json()["id"]

        response = self.client.put(
            f"/api/v1/vendors/{vendor_id}",
            {"name": "Google TPU", "architecture": "TPU v5e", "website": ""},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.get(f"/api/v1/vendors/{vendor_id}").json()["name"],
            "Google TPU",
        )
        response = self.client.delete(f"/api/v1/vendors/{vendor_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_invalid_website_returns_400(self):
        response = self.client.patch(
            f"/api/v1/vendors/{self.vendor.id}", {"website": "nope"}, format="json"
        )
        self.assert_error(response, 400, "validation_error")

    def test_delete_vendor_with_instances_returns_409(self):
        response = self.client.delete(f"/api/v1/vendors/{self.vendor.id}")
        error = self.assert_error(response, 409, "vendor_has_instances")
        self.assertEqual(error["details"], {"instances_count": 2})

    def test_instances_of_vendor(self):
        response = self.client.get(f"/api/v1/vendors/{self.empty_vendor.id}/instances")
        self.assertEqual(response.json(), [])


class ErrorFormatTests(CatalogTestCase):
    def test_unknown_endpoint_returns_json_404(self):
        self.assert_error(self.client.get("/api/v1/unknown"), 404, "not_found")

    def test_method_not_allowed(self):
        self.assert_error(
            self.client.delete("/api/v1/datacenters"), 405, "method_not_allowed"
        )

    def test_malformed_json(self):
        response = self.client.post(
            "/api/v1/vendors", "{bad json", content_type="application/json"
        )
        self.assert_error(response, 400, "parse_error")


class CorsTests(CatalogTestCase):
    def test_frontend_origin_is_allowed(self):
        response = self.client.get(
            "/api/v1/instances", HTTP_ORIGIN="http://localhost:3000"
        )
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "http://localhost:3000"
        )

    def test_unknown_origin_is_not_allowed(self):
        response = self.client.get(
            "/api/v1/instances", HTTP_ORIGIN="http://evil.example.com"
        )
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
