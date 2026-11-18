import logging

from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import (
    IsAdminRoleOrReadOnly,
    IsAuthenticatedOrReadOnly,
    IsAuthenticatedWriteOrAdminDelete,
)

from . import schema
from .exceptions import ConflictError
from .models import Datacenter, HardwareVendor, InstanceType
from .serializers import (
    DatacenterSerializer,
    HardwareVendorSerializer,
    InstanceDetailSerializer,
    InstanceListSerializer,
    InstancePageSerializer,
    InstanceWriteSerializer,
)

logger = logging.getLogger(__name__)


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


def user_label(request):
    """Who performs the action, for log messages (id only, no personal data)."""
    user = request.user
    if user and user.is_authenticated:
        role = "admin" if user.is_staff else "user"
        return f"user_id={user.pk} ({role})"
    return "anonymous"


# --- Base classes shared by datacenters and vendors -------------------------


class ResourceListView(APIView):
    """GET a list of objects / POST a new object."""

    permission_classes = [IsAdminRoleOrReadOnly]
    model = None
    serializer_class = None

    def get(self, request):
        objects = self.model.objects.all()
        serializer = self.serializer_class(objects, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        logger.info(
            "%s created: id=%s name=%r by %s",
            self.model.__name__,
            obj.pk,
            str(obj),
            user_label(request),
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ResourceDetailView(APIView):
    """GET / PUT / PATCH / DELETE a single object."""

    permission_classes = [IsAdminRoleOrReadOnly]
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
        try:
            self.check_can_delete(obj)
        except ConflictError as exc:
            logger.warning(
                "%s id=%s was not deleted by %s: %s",
                self.model.__name__,
                obj.pk,
                user_label(request),
                exc.get_codes(),
            )
            raise
        obj.delete()
        logger.info(
            "%s deleted: id=%s name=%r by %s",
            self.model.__name__,
            pk,
            str(obj),
            user_label(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, pk, partial):
        obj = self.get_object(pk)
        serializer = self.serializer_class(obj, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            "%s updated (%s): id=%s fields=%s by %s",
            self.model.__name__,
            "PATCH" if partial else "PUT",
            obj.pk,
            sorted(serializer.validated_data),
            user_label(request),
        )
        return Response(serializer.data)


class RelatedInstancesView(APIView):
    """GET all instance types that belong to a datacenter / vendor."""

    model = None
    not_found_message = None

    def get(self, request, pk):
        obj = get_object_or_404(self.model.objects.all(), pk, self.not_found_message)
        instances = obj.instances.select_related("datacenter", "vendor")
        return Response(InstanceListSerializer(instances, many=True).data)


def resource_list_schema(tag, name, serializer):
    """Shared OpenAPI description for datacenter / vendor list endpoints."""
    return extend_schema_view(
        get=extend_schema(
            tags=[tag],
            summary=f"Список: {name}",
            operation_id=f"{tag}_list",
            description="Публічний ендпоінт, авторизація не потрібна.",
            auth=[],
        ),
        post=extend_schema(
            tags=[tag],
            summary=f"Створити: {name}",
            description="Доступно лише ролі `admin`.",
            responses={
                201: serializer,
                400: schema.VALIDATION_ERROR,
                401: schema.NOT_AUTHENTICATED,
                403: schema.ADMIN_ONLY,
            },
        ),
    )


def resource_detail_schema(tag, name, serializer, not_found, conflict):
    """Shared OpenAPI description for datacenter / vendor detail endpoints."""
    write_responses = {
        200: serializer,
        400: schema.VALIDATION_ERROR,
        401: schema.NOT_AUTHENTICATED,
        403: schema.ADMIN_ONLY,
        404: not_found,
    }
    return extend_schema_view(
        get=extend_schema(
            tags=[tag],
            summary=f"Деталі: {name}",
            description="Публічний ендпоінт, авторизація не потрібна.",
            auth=[],
            responses={200: serializer, 404: not_found},
        ),
        put=extend_schema(
            tags=[tag],
            summary=f"Повністю оновити: {name}",
            description="Доступно лише ролі `admin`.",
            responses=write_responses,
        ),
        patch=extend_schema(
            tags=[tag],
            summary=f"Частково оновити: {name}",
            description="Доступно лише ролі `admin`.",
            responses=write_responses,
        ),
        delete=extend_schema(
            tags=[tag],
            summary=f"Видалити: {name}",
            description=(
                "Доступно лише ролі `admin`. Об'єкт, з яким пов'язані сервери, "
                "видалити не можна (409)."
            ),
            responses={
                204: OpenApiResponse(description="Об'єкт видалено."),
                401: schema.NOT_AUTHENTICATED,
                403: schema.ADMIN_ONLY,
                404: not_found,
                409: conflict,
            },
        ),
    )


def related_instances_schema(tag, name, not_found):
    return extend_schema(
        tags=[tag],
        summary=f"Сервери, що належать: {name}",
        description="Публічний ендпоінт, авторизація не потрібна.",
        auth=[],
        responses={200: InstanceListSerializer(many=True), 404: not_found},
    )


# --- Datacenters -------------------------------------------------------------

DATACENTER_NOT_FOUND = "Датацентр з id={pk} не знайдено."
DATACENTER_404 = schema.not_found(DATACENTER_NOT_FOUND.format(pk=99))


@resource_list_schema("datacenters", "датацентри", DatacenterSerializer)
class DatacenterListView(ResourceListView):
    model = Datacenter
    serializer_class = DatacenterSerializer


@resource_detail_schema(
    "datacenters",
    "датацентр",
    DatacenterSerializer,
    DATACENTER_404,
    schema.conflict(
        "datacenter_has_instances",
        "Неможливо видалити датацентр «europe-west3-a», оскільки в ньому "
        "розміщено 2 сервери. Спочатку видаліть ці сервери або перенесіть їх "
        "в інший датацентр.",
        count=2,
    ),
)
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


@extend_schema_view(
    get=related_instances_schema("datacenters", "датацентр", DATACENTER_404)
)
class DatacenterInstancesView(RelatedInstancesView):
    model = Datacenter
    not_found_message = DATACENTER_NOT_FOUND


# --- Hardware vendors ----------------------------------------------------------

VENDOR_NOT_FOUND = "Вендора з id={pk} не знайдено."
VENDOR_404 = schema.not_found(VENDOR_NOT_FOUND.format(pk=99))


@resource_list_schema("vendors", "вендори", HardwareVendorSerializer)
class VendorListView(ResourceListView):
    model = HardwareVendor
    serializer_class = HardwareVendorSerializer


@resource_detail_schema(
    "vendors",
    "вендор",
    HardwareVendorSerializer,
    VENDOR_404,
    schema.conflict(
        "vendor_has_instances",
        "Неможливо видалити вендора «NVIDIA», оскільки за ним закріплено "
        "1 сервер. Спочатку видаліть ці сервери або змініть для них вендора.",
    ),
)
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


@extend_schema_view(get=related_instances_schema("vendors", "вендор", VENDOR_404))
class VendorInstancesView(RelatedInstancesView):
    model = HardwareVendor
    not_found_message = VENDOR_NOT_FOUND


# --- Instance types ------------------------------------------------------------

INSTANCE_NOT_FOUND = "Сервер (інстанс) з id={pk} не знайдено."
INSTANCE_404 = schema.not_found(INSTANCE_NOT_FOUND.format(pk=99))

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


INSTANCE_REQUEST_EXAMPLE = OpenApiExample(
    "GPU-сервер",
    value={
        "name": "a2-highgpu-1g",
        "category": "accelerator_optimized",
        "description": "1x NVIDIA A100 для навчання нейромереж",
        "vcpu": 12,
        "ram_gb": 85,
        "gpu_model": "NVIDIA A100 40GB",
        "gpu_count": 1,
        "storage_type": "NVMe SSD",
        "storage_size_gb": 500,
        "network_bandwidth_gbps": 24,
        "hourly_price": "3.67",
        "datacenter_id": 1,
        "vendor_id": 1,
        "is_available": True,
    },
    request_only=True,
)

INSTANCE_RESPONSE_EXAMPLE = OpenApiExample(
    "Збережений сервер",
    value={
        "id": 7,
        "name": "a2-highgpu-1g",
        "category": "accelerator_optimized",
        "description": "1x NVIDIA A100 для навчання нейромереж",
        "vcpu": 12,
        "ram_gb": 85,
        "gpu_model": "NVIDIA A100 40GB",
        "gpu_count": 1,
        "storage_type": "NVMe SSD",
        "storage_size_gb": 500,
        "network_bandwidth_gbps": 24,
        "hourly_price": "3.67",
        "datacenter_id": 1,
        "vendor_id": 1,
        "is_available": True,
        "created_at": "2026-11-18T10:00:00Z",
    },
    response_only=True,
)

INSTANCE_WRITE_DESCRIPTION = (
    "Доступно авторизованим користувачам (ролі `user` і `admin`). "
    "Бізнес-правила: якщо `gpu_count > 0`, потрібно вказати `gpu_model`, і "
    "навпаки; сервер категорії `accelerator_optimized` повинен мати хоча б "
    "один GPU. `datacenter_id` і `vendor_id` мають посилатися на існуючі об'єкти."
)


@extend_schema_view(
    get=extend_schema(
        tags=["instances"],
        summary="Каталог серверів",
        operation_id="instances_list",
        description=(
            "Публічний ендпоінт. Підтримує пошук, фільтрацію, сортування та "
            "пагінацію. Некоректні значення параметрів повертають 400."
        ),
        auth=[],
        parameters=[
            OpenApiParameter(
                "search",
                str,
                description="Пошук за назвою або моделлю GPU (без урахування регістру).",
            ),
            OpenApiParameter(
                "category",
                str,
                enum=InstanceType.Category.values,
                description="Категорія робочого навантаження.",
            ),
            OpenApiParameter("datacenter_id", int, description="id датацентру."),
            OpenApiParameter("vendor_id", int, description="id вендора."),
            OpenApiParameter(
                "sort",
                str,
                enum=list(SORT_FIELDS),
                description="Сортування; `-` перед полем — за спаданням.",
            ),
            OpenApiParameter(
                "page", int, description="Номер сторінки (від 1).", default=1
            ),
            OpenApiParameter(
                "limit",
                int,
                description=f"Елементів на сторінці (1–{MAX_LIMIT}).",
                default=DEFAULT_LIMIT,
            ),
        ],
        responses={200: InstancePageSerializer, 400: schema.VALIDATION_ERROR},
    ),
    post=extend_schema(
        tags=["instances"],
        summary="Додати сервер",
        description=INSTANCE_WRITE_DESCRIPTION,
        request=InstanceWriteSerializer,
        responses={
            201: InstanceWriteSerializer,
            400: schema.VALIDATION_ERROR,
            401: schema.NOT_AUTHENTICATED,
        },
        examples=[INSTANCE_REQUEST_EXAMPLE, INSTANCE_RESPONSE_EXAMPLE],
    ),
)
class InstanceListView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

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

        logger.debug(
            "Instance catalog query: search=%r category=%s datacenter_id=%s "
            "vendor_id=%s sort=%s page=%s limit=%s -> total=%s",
            search,
            category,
            datacenter_id,
            vendor_id,
            sort,
            page,
            limit,
            total,
        )

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
        instance = serializer.save()
        logger.info(
            "InstanceType created: id=%s name=%r datacenter_id=%s vendor_id=%s by %s",
            instance.pk,
            instance.name,
            instance.datacenter_id,
            instance.vendor_id,
            user_label(request),
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


INSTANCE_UPDATE_RESPONSES = {
    200: InstanceWriteSerializer,
    400: schema.VALIDATION_ERROR,
    401: schema.NOT_AUTHENTICATED,
    404: INSTANCE_404,
}


@extend_schema_view(
    get=extend_schema(
        tags=["instances"],
        summary="Деталі сервера",
        description=(
            "Публічний ендпоінт. Повертає повну конфігурацію з вкладеними "
            "об'єктами датацентру та вендора."
        ),
        auth=[],
        responses={200: InstanceDetailSerializer, 404: INSTANCE_404},
    ),
    put=extend_schema(
        tags=["instances"],
        summary="Повністю оновити сервер",
        description=INSTANCE_WRITE_DESCRIPTION + " Потрібно передати всі поля.",
        request=InstanceWriteSerializer,
        responses=INSTANCE_UPDATE_RESPONSES,
        examples=[INSTANCE_REQUEST_EXAMPLE, INSTANCE_RESPONSE_EXAMPLE],
    ),
    patch=extend_schema(
        tags=["instances"],
        summary="Частково оновити сервер",
        description=(
            INSTANCE_WRITE_DESCRIPTION
            + " Передаються лише поля, які треба змінити; бізнес-правила "
            "перевіряються разом із поточними значеннями."
        ),
        request=InstanceWriteSerializer,
        responses=INSTANCE_UPDATE_RESPONSES,
        examples=[
            OpenApiExample(
                "Зняти з оренди та змінити ціну",
                value={"is_available": False, "hourly_price": "2.99"},
                request_only=True,
            ),
            INSTANCE_RESPONSE_EXAMPLE,
        ],
    ),
    delete=extend_schema(
        tags=["instances"],
        summary="Видалити сервер",
        description="Доступно лише ролі `admin`.",
        responses={
            204: OpenApiResponse(description="Сервер видалено."),
            401: schema.NOT_AUTHENTICATED,
            403: schema.ADMIN_ONLY,
            404: INSTANCE_404,
        },
    ),
)
class InstanceDetailView(ResourceDetailView):
    permission_classes = [IsAuthenticatedWriteOrAdminDelete]
    model = InstanceType
    serializer_class = InstanceWriteSerializer
    not_found_message = INSTANCE_NOT_FOUND

    def get_queryset(self):
        return InstanceType.objects.select_related("datacenter", "vendor")

    def get(self, request, pk):
        # Reading returns nested datacenter / vendor objects.
        return Response(InstanceDetailSerializer(self.get_object(pk)).data)


# --- Fallback for unknown API URLs ----------------------------------------------


@extend_schema(exclude=True)
@api_view(["GET", "POST", "PUT", "PATCH", "DELETE"])
def endpoint_not_found(request):
    raise NotFound(
        f"Ендпоінт {request.method} {request.path} не існує. "
        "Перевірте адресу запиту (URL вказуються без кінцевого слеша)."
    )
