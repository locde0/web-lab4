from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("auth/register", views.RegisterView.as_view(), name="register"),
    path("auth/login", views.LoginView.as_view(), name="login"),
    path("auth/refresh", views.TokenRefreshView.as_view(), name="token-refresh"),
    path("users/me", views.CurrentUserView.as_view(), name="current-user"),
]
