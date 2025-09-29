import json
from typing import Any, Dict, Optional, List

from django.conf import settings
from openai import AsyncOpenAI, AsyncStream
from openai.types.responses import ResponseStreamEvent, FileSearchToolParam
from openai.types.vector_store_create_params import ExpiresAfter

from apps.chat.models.chat import ChatRoom
from apps.shared.utils.logger import logger


class AIService:
    def __init__(self):
        self.MODEL_CHEAP = getattr(settings, "OPENAI_MODEL_CHEAP", "gpt-4o-mini")
        self.MODEL_MID = getattr(settings, "OPENAI_MODEL_MID", "gpt-4o-mini")
        self.MODEL_SMART = getattr(settings, "OPENAI_MODEL_SMART", "gpt-4o-mini")

        self.DEFAULT_CONTEXT_MAX_CHARS = int(
            getattr(settings, "CHAT_CONTEXT_MAX_CHARS", 1500)
        )
        self.DEFAULT_EXTRACT_TOKENS = int(
            getattr(settings, "CHAT_EXTRACT_MAX_TOKENS", 200)
        )
        self.DEFAULT_RESPONSE_TOKENS = int(
            getattr(settings, "CHAT_RESPONSE_MAX_TOKENS", 2000)
        )

        self.client: AsyncOpenAI = self._get_openai_client()

    @staticmethod
    def _get_openai_client() -> AsyncOpenAI:
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in settings.")
        return AsyncOpenAI(api_key=api_key)

    async def _responses_create_safe(self, **kwargs) -> Any:
        try:
            if (
                "max_output_tokens" in kwargs
                and kwargs["max_output_tokens"] is not None
            ):
                kwargs["max_output_tokens"] = max(16, int(kwargs["max_output_tokens"]))
        except Exception as e:
            logger.warning(f"Invalid max_output_tokens value: {e}")
            kwargs["max_output_tokens"] = max(16, int(self.DEFAULT_RESPONSE_TOKENS))

        try:
            return await self.client.responses.create(**kwargs)
        except Exception as e:
            logger.exception(f"OpenAI responses.create failed: {e}")
            raise

    @staticmethod
    def truncate_text(text: str, max_chars: int) -> str:
        if not text:
            return ""
        return text[:max_chars]

    async def extract_user_context(self, new_message: str) -> Dict[str, Any]:
        persistent_keys = set(
            getattr(settings, "CHAT_PERSISTENT_KEYS", {"name", "email"})
        )
        keys = ", ".join(persistent_keys)
        system_prompt = (
            "Extract factual user details as a JSON object using short, lowercase keys. "
            "Examples of keys: " + keys + ".\n"
            "Return an empty object if no factual details are found."
        )
        input_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self.truncate_text(new_message, 1000)},
        ]
        try:
            completion = await self._responses_create_safe(
                model=self.MODEL_MID,
                input=input_messages,
                max_output_tokens=self.DEFAULT_EXTRACT_TOKENS,
                text={
                    "format": {"type": "json_object"},
                    "verbosity": "medium",
                },
            )
            response = (
                completion.output[0].content[0].text
                if hasattr(completion, "output")
                else completion
            )
            return response or {}
        except Exception as e:
            logger.warning(f"Context extraction failed: {e}")
            return {}

    async def generate_response(
        self,
        user_message: str,
        specialization_prompt: str,
        user_context: Dict[str, Any],
        chat: Optional[ChatRoom] = None,
        vector_store_id: Optional[str] = None,
    ) -> AsyncStream[ResponseStreamEvent]:
        context_json = self.truncate_text(
            json.dumps(user_context, ensure_ascii=False), self.DEFAULT_CONTEXT_MAX_CHARS
        )
        markdown_system_prompt = (
            "You are a professional technical writer and content creator. Please output your ANSWER in Markdown ONLY. "
            "To use: #, ##, ### for headings, - or * for lists, 1. 2. for numbered lists, "
            "`code` and ``` for block codes. Add sections, summaries, and bullet points. "
            "Do not output any comments or explanations — Markdown only."
        )
        context_prompt = (
            f"{markdown_system_prompt}\n"
            f"Known context: {context_json}\n\n"
            f"{self.truncate_text(specialization_prompt or '', 800)}"
        )
        input_messages = [
            {"role": "system", "content": context_prompt},
            {"role": "user", "content": self.truncate_text(user_message, 1500)},
        ]

        completion = await self._responses_create_safe(
            model=self.MODEL_SMART,
            input=input_messages,
            max_output_tokens=self.DEFAULT_RESPONSE_TOKENS,
            conversation=chat.conversation_id,
            stream=True,
            tools=[
                FileSearchToolParam(
                    type="file_search",
                    vector_store_ids=[vector_store_id],
                )
            ],
        )

        return completion

    async def generate_title(self, full_response: str) -> str:
        system_prompt = "Generate a 3-6 word title for this chat without punctuation."
        input_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self.truncate_text(full_response, 1000)},
        ]
        try:
            completion = await self._responses_create_safe(
                model=self.MODEL_CHEAP,
                input=input_messages,
                max_output_tokens=32,
            )
            title = getattr(completion, "output_text", None) or ""
            return title.strip()
        except Exception as e:
            logger.warning(f"Failed to generate chat title: {e}")
            return ""

    async def create_conversation(self) -> Optional[str]:
        try:
            conversation = await self.client.conversations.create()
            return conversation.id
        except Exception as e:
            logger.warning(f"Failed to create conversation: {e}")
            return None

    async def create_vector_store(self, chat_id: int) -> Optional[str]:
        try:
            vector_store = await self.client.vector_stores.create(
                name=f"chat_{chat_id}_store",
                expires_after=ExpiresAfter(
                    anchor="last_active_at",
                    days=30,
                ),
            )
            return vector_store.id
        except Exception as e:
            logger.warning(f"Failed to create vector store: {e}")
            return None

    async def create_file(self, file) -> Optional[str]:
        try:
            file = await self.client.files.create(file=file, purpose="assistants")
            return file.id
        except Exception as e:
            logger.warning(f"Failed to upload file: {e}")
            return None

    async def add_file_to_vector_store(
        self, chat: ChatRoom, file_ids: List[str]
    ) -> bool:
        try:
            await self.client.vector_stores.file_batches.create(
                vector_store_id=chat.vector_store_id,
                file_ids=file_ids,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to add file to vector store: {e}")
            return False
