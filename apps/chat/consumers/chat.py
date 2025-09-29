import asyncio
import json
from typing import Optional, Union, Dict
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import UntypedToken

from apps.chat.enums.action import FileFormat, WSAction
from apps.chat.enums.ws import WSType
from apps.chat.models.chat import ChatRoom, ChatResource
from apps.chat.models.specializations import Specialization
from apps.chat.services.ai import AIService
from apps.chat.services.chat import ChatService
from apps.chat.services.file import file_service
from apps.shared.utils.logger import logger
from apps.users.models.users import User

DEFAULT_CHUNK_SIZE = int(getattr(settings, "CHAT_CHUNK_SIZE", 512))
DEFAULT_TTL_DAYS = int(getattr(settings, "CHAT_DEFAULT_TTL_DAYS", 30))


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Improved WebSocket consumer using OpenAI Responses API for assistant replies and storing user context.

    Key improvements made compared to the original:
    - Fixed potential "referenced before assignment" bugs for action_type/file_format/file_ids.
    - Moved blocking I/O (file generation) off the event loop using run_in_executor.
    - More robust error handling and logging (including which user/room triggered error).
    - Use database_sync_to_async consistently for ORM operations that are synchronous.
    - Small refactors to keep methods focused and readable.
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
            logger.debug("WebSocket connect rejected: anonymous user")
            return await self.close()

        try:
            self.specialization = await database_sync_to_async(
                lambda u: getattr(u, "specialization", None)
            )(self.user)
        except Exception as e:
            logger.warning(
                f"Failed to load specialization for user {getattr(self.user, 'id', None)}: {e}"
            )
            self.specialization = None

        if not self.specialization:
            logger.debug("WebSocket connect rejected: user has no specialization")
            return await self.close()

        try:
            self.chat = await database_sync_to_async(ChatRoom.objects.get)(
                id=self.room_id
            )
        except ChatRoom.DoesNotExist:
            logger.debug(
                f"WebSocket connect rejected: chat {self.room_id} does not exist"
            )
            return await self.close()
        except Exception as e:
            logger.exception(
                f"Unexpected error while fetching chat {self.room_id}: {e}"
            )
            return await self.close()

        if self.chat.participant_id != self.user.id:
            logger.warning(
                f"WebSocket connect rejected: user {self.user.id} is not participant for chat {self.room_id}"
            )
            return await self.close()

        # Add to group and accept
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        return None

    async def disconnect(self, close_code) -> None:
        if self.room_group_name:
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None) -> None:
        if not text_data:
            return

        payload = json.loads(text_data)
        message_text = (payload.get("message") or "").strip()
        if not message_text:
            return

        file_ids = payload.get("file_ids") if payload.get("file_ids") else None
        action = payload.get("action") or {}

        action_type: Optional[str] = None
        file_format: Optional[str] = None

        if isinstance(action, dict):
            action_type = action.get("type")
            fmt = action.get("format")
            if action_type == WSAction.GENERATE_FILE and fmt in (
                FileFormat.PDF,
                FileFormat.DOCX,
            ):
                file_format = fmt
            else:
                action_type = None
                file_format = None

        try:
            await self.chat_service.save_message(
                self.chat, self.user, message_text, file_ids
            )
        except PermissionError as e:
            logger.warning(f"Message save failed (user {self.user.id}): {e}")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": WSType.ERROR,
                    "message": "Some attached files do not belong to you.",
                },
            )
            return
        except Exception as e:
            logger.exception(
                f"Failed to save user message for user {getattr(self.user, 'id', None)}: {e}"
            )
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": WSType.ERROR,
                    "message": "Could not save your message. Try again.",
                },
            )
            return

        try:
            if await self.chat_service.should_update_context(self.chat):
                await self.chat_service.update_context(
                    self.user, message_text, self.ai_service
                )
        except Exception as e:
            logger.warning(
                f"Context update attempt failed for user {getattr(self.user, 'id', None)}: {e}"
            )

        # Generate and stream AI response
        await self._generate_and_stream_ai_response(
            user_message=message_text,
            vector_store_id=self.chat.vector_store_id,
            action_type=action_type,
            file_format=file_format,
        )

    async def _generate_and_stream_ai_response(
        self,
        user_message: str,
        vector_store_id: Optional[str],
        action_type: Optional[str] = None,
        file_format: Optional[str] = None,
    ) -> None:
        """Generate a response from the AI and stream chunks to the WebSocket group.

        If requested, also generate a file (PDF/DOCX) from the AI's full response using a thread so the
        event loop isn't blocked.
        """
        file_ids = None

        try:
            try:
                allow_storage = bool(self.user.allow_memory_storage)
            except Exception as e:
                logger.debug(
                    f"User {getattr(self.user, 'id', None)} has no profile; defaulting allow_storage=True : {e}"
                )
                allow_storage = True

            user_context: Dict = {}
            full_response: str = ""
            openai_response_id = None

            if allow_storage:
                try:
                    user_context = await self.chat_service.get_user_context(self.user)
                except Exception as e:
                    logger.warning(
                        f"Failed to retrieve user context for user {getattr(self.user, 'id', None)}: {e}"
                    )
                    user_context = {}

            ai_response = await self.ai_service.generate_response(
                user_message=user_message,
                specialization_prompt=getattr(self.specialization, "prompt", "") or "",
                user_context=user_context,
                chat=self.chat,
                vector_store_id=vector_store_id,
            )

            async for event in ai_response:
                openai_response_id = None
                resp = getattr(event, "response", None)
                if resp:
                    openai_response_id = getattr(resp, "id", None)
                etype = getattr(event, "type", None) or (
                    event.get("type") if isinstance(event, dict) else None
                )
                if etype == "response.created":
                    await self.channel_layer.group_send(
                        self.room_group_name, {"type": WSType.AI_START}
                    )
                elif etype == "response.output_text.delta":
                    delta = getattr(event, "delta", None) or event.get("delta")
                    if delta:
                        full_response += delta
                        if not action_type:
                            await self.channel_layer.group_send(
                                self.room_group_name,
                                {"type": WSType.AI_CHUNK, "chunk": delta},
                            )
                elif etype == "error":
                    error_msg = getattr(event, "message", None) or event.get(
                        "message", "An error occurred while generating the AI response."
                    )
                    logger.error(
                        f"AI response error for user {getattr(self.user, 'id', None)} in chat {getattr(self.chat, 'id', None)}: {error_msg}"
                    )
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {"type": WSType.ERROR, "message": error_msg},
                    )

            if full_response:
                if action_type == WSAction.GENERATE_FILE and file_format:
                    try:
                        loop = asyncio.get_running_loop()
                        file_ids = await loop.run_in_executor(
                            None, file_service, full_response, file_format, self.user
                        )
                        if file_ids:
                            for fid in file_ids:
                                try:
                                    file_obj = await database_sync_to_async(
                                        lambda: ChatResource.objects.get(
                                            id=fid, user=self.user
                                        )
                                    )()
                                    if file_obj:
                                        await self.channel_layer.group_send(
                                            self.room_group_name,
                                            {
                                                "type": WSType.AI_FILE,
                                                "file_url": file_obj.file.url,
                                            },
                                        )
                                except ChatResource.DoesNotExist:
                                    logger.warning(
                                        f"Generated file ID {fid} does not exist or does not belong to user {self.user.id}"
                                    )
                                except Exception as e:
                                    logger.exception(
                                        f"Error fetching/generated file {fid} for user {self.user.id}: {e}"
                                    )
                    except Exception as e:
                        logger.exception(
                            f"File generation failed for user {getattr(self.user, 'id', None)}: {e}"
                        )
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                "type": WSType.ERROR,
                                "message": "Failed to generate file from AI response.",
                            },
                        )

                await self.channel_layer.group_send(
                    self.room_group_name, {"type": WSType.AI_END}
                )

                try:
                    ai_msg = await self.chat_service.save_message(
                        chat=self.chat,
                        sender=None,
                        text=full_response,
                        file_ids=file_ids,
                    )
                except Exception as e:
                    logger.exception(
                        f"Failed to save AI message for chat {getattr(self.chat, 'id', None)}: {e}"
                    )
                    ai_msg = None

                if ai_msg and openai_response_id:
                    try:
                        ai_msg.openai_response_id = openai_response_id
                        await database_sync_to_async(ai_msg.save)(
                            update_fields=["openai_response_id"]
                        )
                    except Exception as e:
                        logger.debug(
                            f"Could not persist openai_response_id for message: {e}"
                        )

                try:
                    if self.chat and (
                        not self.chat.name
                        or self.chat.name.lower() in {"new chat", "untitled"}
                    ):
                        new_title = await self.ai_service.generate_title(full_response)
                        if new_title:
                            await self.chat_service.update_chat_name(
                                self.chat, new_title
                            )
                except Exception as e:
                    logger.debug(
                        f"Failed to generate/update chat title for chat {getattr(self.chat, 'id', None)}: {e}"
                    )

        except Exception as e:
            logger.exception(
                f"AI response generation failed for user {getattr(self.user, 'id', None)} in chat {getattr(self.chat, 'id', None)}: {e}"
            )
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": WSType.ERROR,
                    "message": "[⚠️ AI error] Could not generate response. Try again later.",
                },
            )
            await self.channel_layer.group_send(
                self.room_group_name, {"type": WSType.AI_END}
            )

    async def _authenticate_user(self) -> Union[User, AnonymousUser]:
        try:
            qs = parse_qs(self.scope.get("query_string", b"").decode())
            token = (qs.get("token") or qs.get("access_token") or [None])[0]
            if not token:
                return AnonymousUser()

            validated = UntypedToken(token)
            # UntypedToken behaves like a mapping
            user_id = validated.get("user_id")
            return await User.objects.aget(id=user_id) if user_id else AnonymousUser()
        except Exception as e:
            logger.error(f"Authentication error while connecting WS: {e}")
            return AnonymousUser()

    async def ai_chunk(self, event):
        chunk = event.get("chunk", "")
        await self.send(text_data=json.dumps({"type": WSType.AI_CHUNK, "chunk": chunk}))

    async def ai_start(self, event):
        await self.send(text_data=json.dumps({"type": WSType.AI_START}))

    async def ai_end(self, event):
        await self.send(text_data=json.dumps({"type": WSType.AI_END}))

    async def error(self, event):
        message = event.get("message", "An error occurred.")
        await self.send(
            text_data=json.dumps({"type": WSType.ERROR, "message": message})
        )

    async def ai_file(self, event):
        file_url = event.get("file_url", "")
        await self.send(
            text_data=json.dumps({"type": WSType.AI_FILE, "file_url": file_url})
        )
