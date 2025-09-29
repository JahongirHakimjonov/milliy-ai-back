import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError
from openai.types.responses import (
    EasyInputMessageParam,
    ResponseInputTextParam,
    FileSearchToolParam,
)
from openai.types.vector_store_create_params import ExpiresAfter

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

_openai_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY не установлен. Установите переменную окружения или добавьте её в .env файл.\n"
                "Примеры (cmd.exe):\n"
                "  set OPENAI_API_KEY=sk-...\n"
                "Пример (.env):\n"
                "  OPENAI_API_KEY=sk-..."
            )
        _openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


async def stream_and_save_assistant_response(user_message: str) -> str:
    system_prompt: str = "You are a helpful assistant"

    full_content: str = ""

    try:
        messages = [
            EasyInputMessageParam(
                role="system",
                type="message",
                content=[ResponseInputTextParam(text=system_prompt, type="input_text")],
            ),
            EasyInputMessageParam(
                role="user",
                type="message",
                content=[ResponseInputTextParam(text=user_message, type="input_text")],
            ),
        ]

        client: AsyncOpenAI = get_openai_client()

        # file = await client.files.create(
        #     file=open("document.docx", "rb"), purpose="assistants"
        # )
        # print(f"Uploaded file ID: {file}")
        # vector_store_file = await client.vector_stores.create(
        #     # file_ids=[file.id],
        #     expires_after=ExpiresAfter(
        #         anchor="last_active_at",
        #         days=30,
        #     ),
        # )
        # print(f"Uploaded file ID: {vector_store_file}")
        # "vs_68d835f8080c8191ae67ff4e0ad0fb53"
        # "file-Q8F6S9zHsergdrMhzAMFfi"
        # vector_store_file_id = "vs_68d835f8080c8191ae67ff4e0ad0fb53"
        # vector_store_file = await client.vector_stores.file_batches.create(
        #     vector_store_id=vector_store_file_id,
        #     file_ids=["file-Q8F6S9zHsergdrMhzAMFfi"],
        # )
        # print(vector_store_file)

        stream = await client.responses.create(
            model="gpt-4o-mini",
            input=messages,
            conversation="conv_68d8076a547c8193b11390cb11f786cd058ffd8f4288dddd",
            stream=True,
        )

        async for event in stream:
            if event.type == "response.output_text.delta":
                delta = event.delta
                full_content += delta
                print(delta, end="", flush=True)

        print("\n--- Stream complete ---")
        return full_content.strip()

    except (OpenAIError, RuntimeError) as e:
        print(f"\n[Error] {e}")
        return ""
    except Exception as e:
        print(f"\n[Unexpected Error] {type(e).__name__}: {e}")
        return ""


def main():
    if len(sys.argv) > 1:
        user_message = " ".join(sys.argv[1:])
    else:
        user_message = "Summarize the content of the attached document."

    response = asyncio.run(stream_and_save_assistant_response(user_message))
    print(f"\nAssistant's full response:\n{response}")


if __name__ == "__main__":
    main()
