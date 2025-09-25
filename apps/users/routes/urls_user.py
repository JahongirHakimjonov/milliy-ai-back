from django.urls import path

from apps.users.views.me import MeView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
]
