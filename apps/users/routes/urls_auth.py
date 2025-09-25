from django.urls import path

from apps.users.views.custom import (
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
    CustomTokenVerifyView,
)

from apps.users.views.register import RegisterView, ConfirmView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("confirm/", ConfirmView.as_view(), name="confirm"),
    # JWT tokens
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", CustomTokenVerifyView.as_view(), name="token_verify"),
]
