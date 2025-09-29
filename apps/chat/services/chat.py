import json
from typing import Any, Dict, List, Optional

from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from apps.chat.models.chat import ChatRoom, Message, UserContext, ChatResource
from apps.chat.services.ai import AIService
from apps.shared.utils.logger import logger
from apps.users.models.users import User


class ChatService:
    @staticmethod
    async def save_message(
        chat: ChatRoom,
        sender: Optional[User],
        text: str,
        file_ids: Optional[List[int]] = None,
    ) -> Message:
        """
        Save a message to a chat room. Supports ManyToMany file attachments.
        Ensures that attached files belong to the sender.
        """
        try:
            if file_ids:
                allowed = await ChatService.check_files_allowed(sender, file_ids)
                if not allowed:
                    raise PermissionError(
                        "Some attached files do not belong to this user."
                    )

            sender_instance = (
                sender if sender and not isinstance(sender, AnonymousUser) else None
            )

            message = await database_sync_to_async(Message.objects.create)(
                chat=chat,
                sender=sender_instance,
                message=text,
            )

            if file_ids:
                await database_sync_to_async(message.file.set)(file_ids)

            ai_file_ids = (
                await database_sync_to_async(
                    lambda: list(
                        ChatResource.objects.filter(id__in=file_ids).values_list(
                            "file_id", flat=True
                        )
                    )
                )()
                if file_ids
                else []
            )
            if file_ids:
                await AIService().add_file_to_vector_store(
                    chat=chat, file_ids=ai_file_ids
                )
            return message
        except Exception as e:
            logger.error(f"Failed to save message: {e}")
            raise

    @staticmethod
    async def should_update_context(chat: ChatRoom) -> bool:
        total_messages = await database_sync_to_async(
            lambda: Message.objects.filter(chat=chat, sender__isnull=True).count()
        )()
        return total_messages <= 5

    @staticmethod
    async def get_user_context(user: User) -> Dict[str, Any]:
        ctx_obj, _ = await database_sync_to_async(UserContext.objects.get_or_create)(
            user=user
        )
        return await database_sync_to_async(ctx_obj.get_valid_context)()

    @staticmethod
    async def update_context(user: User, new_message: str, ai: AIService) -> None:
        try:
            allow_storage = getattr(user, "allow_memory_storage", True)
        except Exception as e:
            logger.warning(f"User {getattr(user, 'id', 'unknown')} has no profile: {e}")
            allow_storage = True

        if not allow_storage:
            logger.info(
                f"User {user.id} has disabled memory storage; skipping context extraction."
            )
            return

        parsed = await ai.extract_user_context(new_message)

        try:
            parsed = json.loads(parsed) if isinstance(parsed, str) else parsed
        except json.JSONDecodeError:
            logger.debug(f"User {user.id} profile is invalid JSON: {parsed}")
            return

        if not parsed or not isinstance(parsed, dict):
            logger.debug(f"User {user.id} has no profile: {parsed}")
            return

        persistent_keys = set(
            getattr(settings, "CHAT_PERSISTENT_KEYS", {"name", "email"})
        )
        ttl_overrides = getattr(settings, "CHAT_TTL_OVERRIDES", {}) or {}
        priority_map = getattr(settings, "CHAT_PRIORITY_MAP", {})

        ctx_obj, _ = await database_sync_to_async(UserContext.objects.get_or_create)(
            user=user
        )
        await database_sync_to_async(ctx_obj.update_context)(
            parsed,
            source="ai",
            ttl_overrides=ttl_overrides,
            persistent_keys=persistent_keys,
            priority_map=priority_map,
        )

    @staticmethod
    async def update_chat_name(chat: ChatRoom, new_title: str) -> None:
        """
        Update the name of a chat room asynchronously.
        """

        def _update():
            chat.name = new_title
            chat.save(update_fields=["name"])

        await database_sync_to_async(_update)()

    @staticmethod
    async def check_files_allowed(
        user: Optional[User], file_ids: Optional[List[int]]
    ) -> bool:
        if not file_ids or not user or isinstance(user, AnonymousUser):
            return True

        def _check() -> bool:
            try:
                owned_count = ChatResource.objects.filter(
                    user=user, id__in=file_ids
                ).count()
                return owned_count == len(file_ids)
            except Exception as e:
                logger.warning(
                    f"File access check failed for user {getattr(user, 'id', 'unknown')}: {e}"
                )
                return False

        return await database_sync_to_async(_check)()
