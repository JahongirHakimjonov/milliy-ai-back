import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

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
    system_prompt: str = (
        "You are a Python expert with 10 years of experience. "
        "Only answer questions related to Python programming. "
        "If the question is not related to Python, politely refuse."
    )

    full_content: str = ""

    try:
        messages: list[
            ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam
        ] = [
            ChatCompletionSystemMessageParam(role="system", content=system_prompt),
            ChatCompletionUserMessageParam(role="user", content=user_message),
        ]

        client: AsyncOpenAI = get_openai_client()
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            stream=True,
        )

        async for chunk in stream:
            print(chunk)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]

            delta_content = getattr(choice.delta, "content", None)
            if delta_content:
                full_content += delta_content

            if getattr(choice, "finish_reason", None):
                pass

        print("\n--- Stream complete ---")
        return full_content

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
        user_message = "Need hello world example in python."

    if not any(
        word.lower() in user_message.lower()
        for word in ("python", "django", "flask", "asyncio")
    ):
        print(
            "[Info] Заданный вопрос не выглядит связанным с Python. Модель должна будет вежливо отказаться."
        )

    response = asyncio.run(stream_and_save_assistant_response(user_message))
    print(f"\nAssistant's full response:\n{response}")


if __name__ == "__main__":
    main()
