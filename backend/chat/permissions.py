from rest_framework import permissions


class IsTenantAdminOrReadOnly(permissions.BasePermission):
    """Allows read-only access for authenticated users and write access for tenant admins."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False))
