import json
from typing import Optional, Union, Dict, Any
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from apps.chat.models.chat import ChatRoom, Message, UserContext
from apps.chat.models.specializations import Specialization
from apps.shared.utils.logger import logger
from apps.users.models.users import User

MODEL_CHEAP = "gpt-4o-mini"
MODEL_MID = "gpt-4o-mini"
MODEL_SMART = "gpt-4o-mini"

_openai_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client


def truncate_text(text: str, max_chars: int = 1500) -> str:
    """Truncate long strings to reduce token usage."""
    return text[:max_chars]


def approx_token_count(text: str) -> int:
    return len(text) // 4


class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.room_id: Optional[int] = None
        self.room_group_name: Optional[str] = None
        self.user: Union[User, AnonymousUser, None] = None
        self.chat: Optional[ChatRoom] = None
        self.client: AsyncOpenAI = get_openai_client()
        self.specialization: Optional[Specialization] = None

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
            return

        msg_obj = await self._save_message(sender=self.user, text=message_text)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "id": msg_obj.id,
                "message": msg_obj.message,
                "created_at": msg_obj.created_at.isoformat(),
                "sender": {
                    "id": self.user.id,
                    "first_name": self.user.first_name,
                    "last_name": self.user.last_name,
                    "avatar": self.user.avatar.url if self.user.avatar else None,
                },
            },
        )

        if await self._should_update_context():
            await self._extract_and_update_context(message_text)

        await self._generate_and_stream_ai_response(message_text)

    async def _save_message(self, sender, text: str) -> Message:
        sender_instance = (
            sender if sender and not isinstance(sender, AnonymousUser) else None
        )
        return await database_sync_to_async(Message.objects.create)(
            chat=self.chat,
            sender=sender_instance,
            message=text,
        )

    async def _should_update_context(self) -> bool:
        total_messages = await database_sync_to_async(
            Message.objects.filter(chat=self.chat).count
        )()
        return total_messages <= 5

    async def _generate_and_stream_ai_response(self, user_message: str) -> None:
        user_context = await self._get_user_context()
        context_json = truncate_text(json.dumps(user_context, ensure_ascii=False), 1500)

        context_prompt = (
            "You are a helpful assistant. Use known context if relevant.\n"
            f"Known context: {context_json}\n\n"
            f"{truncate_text(self.specialization.prompt, 800)}"
        )

        messages = [
            ChatCompletionSystemMessageParam(role="system", content=context_prompt),
            ChatCompletionUserMessageParam(
                role="user", content=truncate_text(user_message, 1500)
            ),
        ]

        full_response = ""
        try:
            stream = await self.client.chat.completions.create(
                model=MODEL_SMART,
                messages=messages,
                stream=True,
                max_tokens=800,
            )

            async for chunk in stream:
                delta = getattr(chunk.choices[0].delta, "content", None)
                if delta:
                    full_response += delta
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {"type": "ai_chunk", "chunk": delta},
                    )

            await self.channel_layer.group_send(
                self.room_group_name, {"type": "ai_end"}
            )

            if full_response:
                ai_msg = await self._save_message(sender=None, text=full_response)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat_message",
                        "id": ai_msg.id,
                        "message": ai_msg.message,
                        "created_at": ai_msg.created_at.isoformat(),
                        "user": "assistant",
                    },
                )

                total_msgs = await database_sync_to_async(
                    Message.objects.filter(chat=self.chat).count
                )()
                if total_msgs < 3 and (
                    not self.chat.name
                    or self.chat.name.lower() in {"new chat", "untitled"}
                ):
                    new_title = await self._generate_chat_title(full_response)
                    if new_title:
                        await database_sync_to_async(self._update_chat_name)(new_title)

        except Exception as e:
            logger.exception(f"AI response streaming failed: {e}")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "ai_chunk",
                    "chunk": "[⚠️ AI error] Could not generate response. Try again later.",
                },
            )

    async def ai_chunk(self, event):
        await self.send(
            text_data=json.dumps({"type": "ai_chunk", "chunk": event["chunk"]})
        )

    async def ai_end(self, event):
        await self.send(text_data=json.dumps({"type": "ai_end"}))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def _get_user_context(self) -> Dict[str, Any]:
        context, _ = await database_sync_to_async(UserContext.objects.get_or_create)(
            user=self.user
        )
        return context.data or {}

    async def _extract_and_update_context(self, new_message: str):
        system_prompt = "Extract factual user details (name, company, preferences) as JSON. Ignore irrelevant info."

        messages = [
            ChatCompletionSystemMessageParam(role="system", content=system_prompt),
            ChatCompletionUserMessageParam(
                role="user", content=truncate_text(new_message, 1000)
            ),
        ]

        try:
            completion = await self.client.chat.completions.create(
                model=MODEL_MID,
                messages=messages,
                response_format={"type": "json_object"},  # type: ignore
                max_tokens=200,
            )
            content = completion.choices[0].message.content
            try:
                parsed_context = json.loads(content)
                if parsed_context and isinstance(parsed_context, dict):
                    context, _ = await database_sync_to_async(
                        UserContext.objects.get_or_create
                    )(user=self.user)
                    await database_sync_to_async(context.update_context)(parsed_context)
            except Exception as e:
                logger.warning(f"Context JSON parsing failed: {e}")

        except Exception as e:
            logger.warning(f"Context extraction failed: {e}")

    async def _generate_chat_title(self, full_response: str) -> str:
        system_prompt = "Generate a 3-6 word title for this chat without punctuation."
        user_message = truncate_text(full_response, 1000)

        try:
            completion = await self.client.chat.completions.create(
                model=MODEL_CHEAP,
                messages=[
                    ChatCompletionSystemMessageParam(
                        role="system", content=system_prompt
                    ),
                    ChatCompletionUserMessageParam(role="user", content=user_message),
                ],
                max_tokens=15,
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate chat title: {e}")
            return ""

    def _update_chat_name(self, new_title: str):
        self.chat.name = new_title
        self.chat.save(update_fields=["name"])

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
