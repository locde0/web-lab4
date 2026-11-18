"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""

from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from catalog.views import endpoint_not_found

urlpatterns = [
    # The backend has no HTML pages: the root opens the API documentation.
    path("", RedirectView.as_view(pattern_name="swagger-ui", permanent=False)),
    path("admin/", admin.site.urls),
    # OpenAPI 3 schema (YAML by default, JSON with ?format=json) and its UIs.
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/redoc", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/v1/", include("users.urls")),
    path("api/v1/", include("catalog.urls")),
    # Any other /api/... URL returns a JSON 404 in the common error format.
    re_path(r"^api/", endpoint_not_found),
]
