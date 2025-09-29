from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.chat.models.chat import ChatRoom, Message, ChatResource, UserContext


@admin.register(ChatRoom)
class ChatRoomAdmin(ModelAdmin):
    list_display = ("id", "name", "created_at", "updated_at")
    autocomplete_fields = ("participant",)
    search_fields = ("participant__email",)
    readonly_fields = (
        "conversation_id",
        "vector_store_id",
        "created_at",
        "updated_at",
    )


@admin.register(Message)
class MessageAdmin(ModelAdmin):
    list_display = ("id", "chat", "sender", "message", "created_at")
    search_fields = ("chat__participant__email", "sender__email")
    autocomplete_fields = ("chat", "sender", "file")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("chat", "sender")


@admin.register(ChatResource)
class ChatResourceAdmin(ModelAdmin):
    list_display = ("id", "user", "file", "created_at")
    autocomplete_fields = ("user",)
    search_fields = ("file", "user__first_name")
    readonly_fields = ("file_id", "name", "size", "type", "created_at")


@admin.register(UserContext)
class UserContextAdmin(ModelAdmin):
    list_display = ("id", "user", "created_at")
    autocomplete_fields = ("user",)
    search_fields = ("user__first_name",)
    readonly_fields = ("created_at", "data")
