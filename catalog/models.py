from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Datacenter(models.Model):
    """Physical location (zone) where compute instances are hosted."""

    name = models.CharField(max_length=64, unique=True)
    region_code = models.CharField(max_length=64)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    sla_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("99.99"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "datacenters"
        ordering = ["id"]

    def __str__(self):
        return self.name


class HardwareVendor(models.Model):
    """Manufacturer / architecture of the hardware that powers instances."""

    name = models.CharField(max_length=100, unique=True)
    architecture = models.CharField(max_length=150)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hardware_vendors"
        ordering = ["id"]

    def __str__(self):
        return self.name


class InstanceType(models.Model):
    """Server configuration that can be rented from the catalog."""

    class Category(models.TextChoices):
        GENERAL = "general", "General-Purpose"
        COMPUTE_OPTIMIZED = "compute_optimized", "Compute-Optimized"
        ACCELERATOR_OPTIMIZED = "accelerator_optimized", "Accelerator-Optimized"

    class StorageType(models.TextChoices):
        HDD = "HDD", "HDD"
        SSD = "SSD", "SSD"
        NVME_SSD = "NVMe SSD", "NVMe SSD"

    name = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=32, choices=Category.choices)
    description = models.TextField(blank=True)
    vcpu = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    ram_gb = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    gpu_model = models.CharField(max_length=100, blank=True)
    gpu_count = models.PositiveIntegerField(default=0)
    storage_type = models.CharField(max_length=16, choices=StorageType.choices)
    storage_size_gb = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    network_bandwidth_gbps = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    hourly_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    is_available = models.BooleanField(default=True)
    # PROTECT: a datacenter or vendor cannot be removed while instances
    # still reference it (the API reports this as 409 Conflict).
    datacenter = models.ForeignKey(
        Datacenter, on_delete=models.PROTECT, related_name="instances"
    )
    vendor = models.ForeignKey(
        HardwareVendor, on_delete=models.PROTECT, related_name="instances"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "instance_types"
        ordering = ["id"]

    def __str__(self):
        return self.name
