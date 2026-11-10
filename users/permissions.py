from rest_framework.permissions import SAFE_METHODS, BasePermission

ADMIN_REQUIRED_MESSAGE = (
    "У вас недостатньо прав для виконання цієї дії. "
    "Ця операція доступна лише адміністраторам платформи."
)


class IsAuthenticatedOrReadOnly(BasePermission):
    """Allow read-only access to anyone, and write access to authenticated users."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)


class IsAdminRoleOrReadOnly(BasePermission):
    """Allow read-only access to anyone, and write access only to staff admins."""

    message = ADMIN_REQUIRED_MESSAGE

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user and request.user.is_authenticated and request.user.is_staff
        )


class IsAuthenticatedWriteOrAdminDelete(BasePermission):
    """Allow reading to anyone, updating to authenticated users, and deleting only to admins."""

    message = ADMIN_REQUIRED_MESSAGE

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method == "DELETE":
            return bool(request.user.is_staff)
        return True
