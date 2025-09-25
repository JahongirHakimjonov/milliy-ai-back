import mimetypes

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.encoders.encoder import PrettyJSONEncoder
from apps.shared.models.base import AbstractBaseModel


class ChatResource(AbstractBaseModel):
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="chat_resources",
        help_text="Foydalanuvchi.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Fayl nomi.",
    )
    file = models.FileField(
        upload_to="chat_resources/",
        help_text="Foydalanuvchi yuborgan fayl.",
    )
    size = models.PositiveBigIntegerField(
        help_text="Fayl hajmi (byte).", null=True, blank=True
    )
    type = models.CharField(
        max_length=255, help_text="Fayl turi.", null=True, blank=True
    )

    def __str__(self):
        return str(self.file.name)

    def save(self, *args, **kwargs):
        self.size = self.file.size
        self.type, _ = mimetypes.guess_type(self.file.name)
        self.name = self.file.name
        super().save(*args, **kwargs)


class ChatRoom(AbstractBaseModel):
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Chat nomi.",
        default="New Chat",
    )
    participant = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="chat_rooms",
        help_text="Chat xonasi yaratilgan foydalanuvchi.",
    )

    def __str__(self):
        return f"Chat {self.id} - {self.participant.email}"

    class Meta:
        verbose_name = _("Chat Room")
        verbose_name_plural = _("Chat Rooms")
        ordering = ["-updated_at"]
        db_table = "chat_rooms"


class Message(AbstractBaseModel):
    chat = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="Xabar tegishli bo'lgan chat xonasi.",
    )
    sender = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        help_text="Xabarni yuborgan foydalanuvchi.",
        related_name="sent_messages",
        null=True,
        blank=True,
    )
    message = models.TextField(blank=True, null=True, help_text="Xabar matni.")
    file = models.ForeignKey(
        "ChatResource", null=True, blank=True, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.message[:30] if self.message else 'File Message'}"

    class Meta:
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")
        ordering = ["created_at"]
        db_table = "messages"


class UserContext(AbstractBaseModel):
    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        related_name="context",
        help_text="Foydalanuvchining muhim konteksti (AI uchun).",
    )
    data = models.JSONField(
        default=dict,
        help_text="AI uchun foydali kontekst ma'lumotlari.",
        encoder=PrettyJSONEncoder,
    )

    def update_context(self, new_data: dict):
        self.data.update(new_data)
        self.save()

    def __str__(self):
        return f"Context for {self.user.email}"

    class Meta:
        verbose_name = _("User Context")
        verbose_name_plural = _("User Contexts")
        db_table = "user_contexts"
