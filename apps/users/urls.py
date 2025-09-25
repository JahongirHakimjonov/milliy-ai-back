from django.urls import path, include

app_name = "users"

urlpatterns = [
    path("user/", include("apps.users.routes.urls_user")),
    path("auth/", include("apps.users.routes.urls_auth")),
]
