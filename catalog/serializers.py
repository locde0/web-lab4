from rest_framework import serializers

from .models import Datacenter, HardwareVendor, InstanceType


class BlankAsNullCharField(serializers.CharField):
    """Optional text stored as "" in the DB but shown as null in JSON.

    Django recommends not using null=True on CharField, while the API
    contract uses null for "no value" (e.g. an instance without GPU).
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def validate_empty_values(self, data):
        if data is None:
            return True, ""
        return super().validate_empty_values(data)

    def to_representation(self, value):
        return value or None


# --- Datacenters -----------------------------------------------------------


class DatacenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Datacenter
        fields = [
            "id",
            "name",
            "region_code",
            "city",
            "country",
            "sla_percent",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class DatacenterShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Datacenter
        fields = ["id", "name", "city"]


class DatacenterNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Datacenter
        fields = ["id", "name", "region_code", "city", "country"]


# --- Hardware vendors ------------------------------------------------------


class HardwareVendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = HardwareVendor
        fields = ["id", "name", "architecture", "website", "created_at"]
        read_only_fields = ["id", "created_at"]


class HardwareVendorShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = HardwareVendor
        fields = ["id", "name"]


class HardwareVendorNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = HardwareVendor
        fields = ["id", "name", "architecture"]


# --- Instance types --------------------------------------------------------


class InstanceListSerializer(serializers.ModelSerializer):
    """Compact representation used in catalog lists."""

    datacenter = DatacenterShortSerializer(read_only=True)
    vendor = HardwareVendorShortSerializer(read_only=True)
    gpu_model = BlankAsNullCharField(read_only=True)

    class Meta:
        model = InstanceType
        fields = [
            "id",
            "name",
            "category",
            "vcpu",
            "ram_gb",
            "gpu_model",
            "gpu_count",
            "hourly_price",
            "datacenter",
            "vendor",
            "is_available",
        ]


class InstanceDetailSerializer(serializers.ModelSerializer):
    """Full representation of one instance type with nested relations."""

    datacenter = DatacenterNestedSerializer(read_only=True)
    vendor = HardwareVendorNestedSerializer(read_only=True)
    gpu_model = BlankAsNullCharField(read_only=True)

    class Meta:
        model = InstanceType
        fields = [
            "id",
            "name",
            "category",
            "description",
            "vcpu",
            "ram_gb",
            "gpu_model",
            "gpu_count",
            "storage_type",
            "storage_size_gb",
            "network_bandwidth_gbps",
            "hourly_price",
            "is_available",
            "datacenter",
            "vendor",
            "created_at",
        ]


class InstanceWriteSerializer(serializers.ModelSerializer):
    """Used for POST / PUT / PATCH: relations are passed as plain ids."""

    gpu_model = BlankAsNullCharField(max_length=100)
    datacenter_id = serializers.PrimaryKeyRelatedField(
        source="datacenter",
        queryset=Datacenter.objects.all(),
        error_messages={
            "does_not_exist": "Датацентр з id={pk_value} не існує.",
        },
    )
    vendor_id = serializers.PrimaryKeyRelatedField(
        source="vendor",
        queryset=HardwareVendor.objects.all(),
        error_messages={
            "does_not_exist": "Вендор з id={pk_value} не існує.",
        },
    )

    class Meta:
        model = InstanceType
        fields = [
            "id",
            "name",
            "category",
            "description",
            "vcpu",
            "ram_gb",
            "gpu_model",
            "gpu_count",
            "storage_type",
            "storage_size_gb",
            "network_bandwidth_gbps",
            "hourly_price",
            "datacenter_id",
            "vendor_id",
            "is_available",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        # For PATCH some fields may be missing: fall back to current values.
        def current(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, default)

        gpu_model = current("gpu_model")
        gpu_count = current("gpu_count", 0)
        category = current("category")

        errors = {}
        if gpu_count > 0 and not gpu_model:
            errors["gpu_model"] = [
                "Вкажіть модель GPU, якщо gpu_count більше нуля.",
            ]
        if gpu_count == 0 and gpu_model:
            errors["gpu_count"] = [
                "Для вказаної моделі GPU кількість прискорювачів має бути не менше 1.",
            ]
        if category == InstanceType.Category.ACCELERATOR_OPTIMIZED and gpu_count < 1:
            errors.setdefault("gpu_count", []).append(
                "Інстанс категорії accelerator_optimized повинен мати хоча б один GPU."
            )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
