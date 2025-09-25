from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter

from apps.users.models.sms import SmsConfirm


@admin.register(SmsConfirm)
class SmsConfirmAdmin(ModelAdmin):
    list_display = ["id", "email", "code", "try_count", "created_at"]
    search_fields = ["email"]
    list_filter = [("created_at", RangeDateFilter)]
    ordering = ["-created_at"]
    readonly_fields = ["email", "code", "created_at"]
    fieldsets = ((None, {"fields": ("email", "code", "created_at")}),)
    add_fieldsets = ((None, {"fields": ("email", "code")}),)
    list_filter_submit = True
