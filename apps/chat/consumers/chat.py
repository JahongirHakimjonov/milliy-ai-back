import json
from typing import Optional, Union
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from apps.chat.models.chat import ChatRoom
from apps.chat.models.specializations import Specialization
from apps.chat.services.ai import AIService
from apps.chat.services.chat import ChatService
from apps.shared.utils.logger import logger
from apps.users.models.users import User

DEFAULT_CHUNK_SIZE = int(getattr(settings, "CHAT_CHUNK_SIZE", 512))
DEFAULT_TTL_DAYS = int(getattr(settings, "CHAT_DEFAULT_TTL_DAYS", 30))


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer using OpenAI Responses API for assistant replies and storing user context.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.room_id: Optional[int] = None
        self.room_group_name: Optional[str] = None
        self.user: Union[User, AnonymousUser, None] = None
        self.chat: Optional[ChatRoom] = None
        self.specialization: Optional[Specialization] = None
        self.ai_service = AIService()
        self.chat_service = ChatService()

    async def connect(self) -> None:
        self.room_id = self.scope["url_route"]["kwargs"].get("room_id")
        self.room_group_name = f"chat_{self.room_id}"
        self.user = await self._authenticate_user()

        if not self.user or isinstance(self.user, AnonymousUser):
            return await self.close()

        self.specialization = await database_sync_to_async(
            lambda u: getattr(u, "specialization", None)
        )(self.user)
        if not self.specialization:
            return await self.close()

        try:
            self.chat = await database_sync_to_async(ChatRoom.objects.get)(
                id=self.room_id
            )
        except ChatRoom.DoesNotExist:
            return await self.close()

        if self.chat.participant_id != self.user.id:
            return await self.close()

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        return None

    async def disconnect(self, close_code) -> None:
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None) -> None:
        if not text_data:
            return

        payload = json.loads(text_data)
        message_text = (payload.get("message") or "").strip()
        if not message_text:
            message_text = (
                "You are an intelligent assistant that processes voice messages sent by the user (converted into text). "
                "Your task is as follows:\n"
                "1. Briefly analyze the content of the user's message (what they are asking or saying).\n"
                "2. If you detect a specific tone (polite, serious, friendly, etc.), adjust your response to match that tone.\n"
                "3. Write a polite, natural, and concise text response to the user.\n"
                "4. Never repeat or quote the voice transcription — only provide your response.\n"
                "5. Always write the response naturally, as if you were having a real conversation with a human."
            )

        file_ids = payload.get("file_ids") if payload.get("file_ids") else None

        try:
            await self.chat_service.save_message(
                self.chat, self.user, message_text, file_ids
            )
        except PermissionError as e:
            logger.warning(f"Message save failed due to permission error: {e}")
            await self.send(
                text_data=json.dumps(
                    {"error": "Some attached files do not belong to you."}
                )
            )
            return
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
            await self.send(
                text_data=json.dumps(
                    {"error": "Could not save your message. Try again."}
                )
            )
            return

        try:
            if await self.chat_service.should_update_context(self.chat):
                await self.chat_service.update_context(
                    self.user, message_text, self.ai_service
                )
        except Exception as e:
            logger.warning(f"Context update attempt failed: {e}")

        await self._generate_and_stream_ai_response(
            message_text, self.chat.vector_store_id
        )

    async def _generate_and_stream_ai_response(
        self, user_message: str, vector_store_id: Optional[str]
    ) -> None:
        try:
            try:
                allow_storage = bool(self.user.allow_memory_storage)
            except Exception as e:
                logger.warning(f"User {self.user.id} has no profile: {e}")
                allow_storage = True

            user_context = {}
            full_response: str = ""
            if allow_storage:
                try:
                    user_context = await self.chat_service.get_user_context(self.user)
                except Exception as e:
                    logger.warning(
                        f"Failed to retrieve user context for user {self.user.id}: {e}"
                    )
                    user_context = {}

            stream, openai_response_id = await self.ai_service.generate_response(
                user_message=user_message,
                specialization_prompt=getattr(self.specialization, "prompt", "") or "",
                user_context=user_context,
                chat=self.chat,
                vector_store_id=vector_store_id,
            )

            await self.channel_layer.group_send(
                self.room_group_name, {"type": "ai_start"}
            )

            async for event in stream:
                if event.type == "response.output_text.delta":
                    delta = event.delta
                    full_response += delta
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {"type": "ai_chunk", "chunk": delta},
                    )

            if full_response:
                await self.channel_layer.group_send(
                    self.room_group_name, {"type": "ai_end"}
                )
                ai_msg = await self.chat_service.save_message(
                    self.chat, None, full_response
                )
                if openai_response_id:
                    try:
                        ai_msg.openai_response_id = openai_response_id
                        await database_sync_to_async(ai_msg.save)(
                            update_fields=["openai_response_id"]
                        )
                    except Exception as e:
                        logger.debug(
                            f"Could not save openai_response_id on Message (field may not exist): {e}"
                        )

                if not self.chat.name or self.chat.name.lower() in {
                    "new chat",
                    "untitled",
                }:
                    new_title = await self.ai_service.generate_title(full_response)
                    if new_title:
                        await self.chat_service.update_chat_name(self.chat, new_title)

        except Exception as e:
            logger.exception(f"AI response generation failed: {e}")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "ai_chunk",
                    "chunk": "[⚠️ AI error] Could not generate response. Try again later.",
                },
            )
            await self.channel_layer.group_send(
                self.room_group_name, {"type": "ai_end"}
            )

    async def _authenticate_user(self) -> Union[User, AnonymousUser]:
        try:
            qs = parse_qs(self.scope.get("query_string", b"").decode())
            token = (qs.get("token") or qs.get("access_token") or [None])[0]
            if not token:
                return AnonymousUser()

            from rest_framework_simplejwt.tokens import UntypedToken

            validated = UntypedToken(token)
            user_id = validated.get("user_id")
            return await User.objects.aget(id=user_id) if user_id else AnonymousUser()
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return AnonymousUser()

    async def ai_chunk(self, event):
        chunk = event.get("chunk", "")
        await self.send(text_data=json.dumps({"type": "ai_chunk", "chunk": chunk}))

    async def ai_start(self, event):
        await self.send(text_data=json.dumps({"type": "ai_start"}))

    async def ai_end(self, event):
        await self.send(text_data=json.dumps({"type": "ai_end"}))
