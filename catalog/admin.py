from django.contrib import admin

from .models import Datacenter, HardwareVendor, InstanceType


@admin.register(Datacenter)
class DatacenterAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "region_code", "city", "country", "sla_percent")
    search_fields = ("name", "city", "country")


@admin.register(HardwareVendor)
class HardwareVendorAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "architecture", "website")
    search_fields = ("name",)


@admin.register(InstanceType)
class InstanceTypeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
        "vcpu",
        "ram_gb",
        "gpu_model",
        "hourly_price",
        "is_available",
        "datacenter",
        "vendor",
    )
    list_filter = ("category", "is_available", "datacenter", "vendor")
    search_fields = ("name", "gpu_model")
