import mimetypes
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.db import models
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _

from apps.shared.encoders.encoder import PrettyJSONEncoder
from apps.shared.models.base import AbstractBaseModel
from apps.shared.utils.logger import logger

DEFAULT_TTL_DAYS = int(getattr(settings, "CHAT_DEFAULT_TTL_DAYS", 30))


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
    file_id = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="OpenAI fayl ID.",
        db_index=True,
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
    conversation_id = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="Chat xonasi id.",
    )
    vector_store_id = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="Vector stores id.",
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
    file = models.ManyToManyField(
        ChatResource,
        blank=True,
        related_name="messages",
        help_text="Xabar bilan birga yuborilgan fayllar.",
    )
    openai_response_id = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
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
        "users.User", on_delete=models.CASCADE, related_name="user_context"
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        encoder=PrettyJSONEncoder,
        help_text="AI uchun foydalanuvchi ma'lumotlari.",
    )

    def _now(self):
        return dj_timezone.now()

    def _iso(self, dt):
        if not dt:
            return None
        return dt.isoformat()

    def get_valid_context(self) -> dict:
        """
        Return a simple dict of key->value for non-expired entries.
        """
        now = self._now()
        result = {}
        changed = False
        for k, meta in (self.data or {}).items():
            expires = meta.get("expires_at")
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(expires)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                except Exception as e:
                    logger.warning(f"Failed to parse expires_at for key {k}: {e}")
                    exp_dt = None
            else:
                exp_dt = None

            if exp_dt and exp_dt < now:
                changed = True
                continue

            result[k] = meta.get("value")
        if changed:
            # optionally prune expired entries from stored data (non-blocking)
            self.prune_expired()  # uncomment if you want immediate pruning
            pass
        return result

    def prune_expired(self) -> None:
        """
        Permanently remove expired keys from `self.data`.
        """
        now = self._now()
        new = {}
        changed = False
        for k, meta in (self.data or {}).items():
            expires = meta.get("expires_at")
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(expires)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                except Exception as e:
                    logger.warning(f"Failed to parse expires_at for key {k}: {e}")
                    exp_dt = None
            else:
                exp_dt = None

            if exp_dt and exp_dt < now:
                changed = True
                continue
            new[k] = meta
        if changed:
            self.data = new
            self.save(update_fields=["data"])

    def update_context(
        self,
        incoming: dict,
        *,
        source: str = "ai",
        ttl_overrides: dict = None,
        persistent_keys: set = None,
        priority_map: dict = None,
    ) -> None:
        """
        Merge incoming dict of facts into saved context.

        incoming: {"name": "Jahongir", "likes": ["tea", "coffee"]}
        ttl_overrides: {"likes": 7}  # days TTL per key
        persistent_keys: set(["name"])  # keys that shouldn't expire (persistent)
        priority_map: {"name": 100}  # bigger -> higher priority (used for conflict resolution)
        """
        if ttl_overrides is None:
            ttl_overrides = {}
        if persistent_keys is None:
            persistent_keys = set()
        if priority_map is None:
            priority_map = {}

        now = self._now()
        data = self.data or {}

        for key, value in incoming.items():
            # canonicalize simple types -> keep as-is
            existing = data.get(key)
            existing_priority = existing.get("priority", 0) if existing else 0
            new_priority = priority_map.get(key, existing_priority or 0)

            # If incoming has explicit priority (rare), allow it
            if isinstance(value, dict) and "value" in value and "priority" in value:
                # accept a structured incoming entry
                v = value["value"]
                new_priority = value.get("priority", new_priority)
            else:
                v = value

            if existing and existing_priority > new_priority:
                expires = existing.get("expires_at")
                expired = False
                if expires:
                    try:
                        exp_dt = datetime.fromisoformat(expires)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        expired = exp_dt < now
                    except Exception as e:
                        logger.warning(f"Failed to parse expires_at for key {key}: {e}")
                        expired = False
                if not expired:
                    continue

            if key in persistent_keys:
                expires_at = None
                persistent = True
            else:
                days = ttl_overrides.get(key, DEFAULT_TTL_DAYS)
                expires_at = (now + timedelta(days=int(days))).isoformat()
                persistent = False

            data[key] = {
                "value": v,
                "updated_at": now.isoformat(),
                "expires_at": expires_at,
                "persistent": bool(persistent),
                "priority": int(new_priority),
                "source": source,
            }

        self.data = data
        self.save(update_fields=["data"])

    def __str__(self):
        return f"Context for {self.user.email}"

    class Meta:
        verbose_name = _("User Context")
        verbose_name_plural = _("User Contexts")
        db_table = "user_contexts"
