from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.chat.models.specializations import Specialization


@admin.register(Specialization)
class SpecializationAdmin(ModelAdmin):
    list_display = ("id", "name", "image")
    search_fields = ("name",)
    list_filter = ("created_at",)
    list_filter_submit = True
