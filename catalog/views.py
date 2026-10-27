from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import ConflictError
from .models import Datacenter, HardwareVendor, InstanceType
from .serializers import (
    DatacenterSerializer,
    HardwareVendorSerializer,
    InstanceDetailSerializer,
    InstanceListSerializer,
    InstanceWriteSerializer,
)


def plural_uk(count, forms):
    """Pick the Ukrainian plural form: ("сервер", "сервери", "серверів")."""
    if count % 10 == 1 and count % 100 != 11:
        form = forms[0]
    elif 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        form = forms[1]
    else:
        form = forms[2]
    return f"{count} {form}"


SERVER_FORMS = ("сервер", "сервери", "серверів")


def get_object_or_404(queryset, pk, message):
    """Like django.shortcuts.get_object_or_404, but with a clear message."""
    try:
        return queryset.get(pk=pk)
    except queryset.model.DoesNotExist:
        raise NotFound(message.format(pk=pk)) from None


# --- Base classes shared by datacenters and vendors -------------------------


class ResourceListView(APIView):
    """GET a list of objects / POST a new object."""

    model = None
    serializer_class = None

    def get(self, request):
        objects = self.model.objects.all()
        serializer = self.serializer_class(objects, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ResourceDetailView(APIView):
    """GET / PUT / PATCH / DELETE a single object."""

    model = None
    serializer_class = None
    not_found_message = "Об'єкт з id={pk} не знайдено."

    def get_queryset(self):
        return self.model.objects.all()

    def get_object(self, pk):
        return get_object_or_404(self.get_queryset(), pk, self.not_found_message)

    def check_can_delete(self, obj):
        """Raise ConflictError if the object must not be deleted."""

    def get(self, request, pk):
        serializer = self.serializer_class(self.get_object(pk))
        return Response(serializer.data)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def delete(self, request, pk):
        obj = self.get_object(pk)
        self.check_can_delete(obj)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, pk, partial):
        obj = self.get_object(pk)
        serializer = self.serializer_class(obj, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RelatedInstancesView(APIView):
    """GET all instance types that belong to a datacenter / vendor."""

    model = None
    not_found_message = None

    def get(self, request, pk):
        obj = get_object_or_404(self.model.objects.all(), pk, self.not_found_message)
        instances = obj.instances.select_related("datacenter", "vendor")
        return Response(InstanceListSerializer(instances, many=True).data)


# --- Datacenters -------------------------------------------------------------

DATACENTER_NOT_FOUND = "Датацентр з id={pk} не знайдено."


class DatacenterListView(ResourceListView):
    model = Datacenter
    serializer_class = DatacenterSerializer


class DatacenterDetailView(ResourceDetailView):
    model = Datacenter
    serializer_class = DatacenterSerializer
    not_found_message = DATACENTER_NOT_FOUND

    def check_can_delete(self, obj):
        count = obj.instances.count()
        if count:
            raise ConflictError(
                f"Неможливо видалити датацентр «{obj.name}», оскільки в ньому "
                f"розміщено {plural_uk(count, SERVER_FORMS)}. Спочатку видаліть "
                f"ці сервери або перенесіть їх в інший датацентр.",
                code="datacenter_has_instances",
                details={"instances_count": count},
            )


class DatacenterInstancesView(RelatedInstancesView):
    model = Datacenter
    not_found_message = DATACENTER_NOT_FOUND


# --- Hardware vendors ----------------------------------------------------------

VENDOR_NOT_FOUND = "Вендора з id={pk} не знайдено."


class VendorListView(ResourceListView):
    model = HardwareVendor
    serializer_class = HardwareVendorSerializer


class VendorDetailView(ResourceDetailView):
    model = HardwareVendor
    serializer_class = HardwareVendorSerializer
    not_found_message = VENDOR_NOT_FOUND

    def check_can_delete(self, obj):
        count = obj.instances.count()
        if count:
            raise ConflictError(
                f"Неможливо видалити вендора «{obj.name}», оскільки за ним "
                f"закріплено {plural_uk(count, SERVER_FORMS)}. Спочатку видаліть "
                f"ці сервери або змініть для них вендора.",
                code="vendor_has_instances",
                details={"instances_count": count},
            )


class VendorInstancesView(RelatedInstancesView):
    model = HardwareVendor
    not_found_message = VENDOR_NOT_FOUND


# --- Instance types ------------------------------------------------------------

INSTANCE_NOT_FOUND = "Сервер (інстанс) з id={pk} не знайдено."

SORT_FIELDS = {
    "price": "hourly_price",
    "-price": "-hourly_price",
    "ram_gb": "ram_gb",
    "-ram_gb": "-ram_gb",
}
DEFAULT_LIMIT = 10
MAX_LIMIT = 100


def parse_positive_int(params, name, errors, default=None, maximum=None):
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        errors[name] = ["Значення має бути цілим числом."]
        return default
    if value < 1:
        errors[name] = ["Значення має бути не менше 1."]
    elif maximum is not None and value > maximum:
        errors[name] = [f"Значення має бути не більше {maximum}."]
    return value


class InstanceListView(APIView):
    def get(self, request):
        params = request.query_params
        errors = {}

        category = params.get("category")
        if category and category not in InstanceType.Category.values:
            allowed = ", ".join(InstanceType.Category.values)
            errors["category"] = [f"Допустимі значення: {allowed}."]

        sort = params.get("sort")
        if sort and sort not in SORT_FIELDS:
            errors["sort"] = [f"Допустимі значення: {', '.join(SORT_FIELDS)}."]

        datacenter_id = parse_positive_int(params, "datacenter_id", errors)
        vendor_id = parse_positive_int(params, "vendor_id", errors)
        page = parse_positive_int(params, "page", errors, default=1)
        limit = parse_positive_int(
            params, "limit", errors, default=DEFAULT_LIMIT, maximum=MAX_LIMIT
        )

        if errors:
            raise ValidationError(errors)

        queryset = InstanceType.objects.select_related("datacenter", "vendor")
        search = params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(gpu_model__icontains=search)
            )
        if category:
            queryset = queryset.filter(category=category)
        if datacenter_id:
            queryset = queryset.filter(datacenter_id=datacenter_id)
        if vendor_id:
            queryset = queryset.filter(vendor_id=vendor_id)
        if sort:
            queryset = queryset.order_by(SORT_FIELDS[sort], "id")

        total = queryset.count()
        offset = (page - 1) * limit
        results = queryset[offset : offset + limit]

        return Response(
            {
                "total": total,
                "page": page,
                "limit": limit,
                "results": InstanceListSerializer(results, many=True).data,
            }
        )

    def post(self, request):
        serializer = InstanceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class InstanceDetailView(ResourceDetailView):
    model = InstanceType
    serializer_class = InstanceWriteSerializer
    not_found_message = INSTANCE_NOT_FOUND

    def get_queryset(self):
        return InstanceType.objects.select_related("datacenter", "vendor")

    def get(self, request, pk):
        # Reading returns nested datacenter / vendor objects.
        return Response(InstanceDetailSerializer(self.get_object(pk)).data)


# --- Fallback for unknown API URLs ----------------------------------------------


@api_view(["GET", "POST", "PUT", "PATCH", "DELETE"])
def endpoint_not_found(request):
    raise NotFound(
        f"Ендпоінт {request.method} {request.path} не існує. "
        "Перевірте адресу запиту (URL вказуються без кінцевого слеша)."
    )
