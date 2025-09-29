import asyncio
from typing import Optional

from openai import AsyncOpenAI
from openai.types.responses import (
    EasyInputMessageParam,
    ResponseInputTextParam,
)

from dev import get_openai_client

client: AsyncOpenAI = get_openai_client()


async def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as audio_file:
        transcript = await client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=audio_file,
            response_format="text",
        )
    return transcript


async def get_ai_response(user_text: Optional[str] = None) -> str:
    system_prompt = (
        "You are an intelligent assistant that processes voice messages (converted into text) "
        "and replies naturally and politely in conversation style."
    )

    messages = [
        EasyInputMessageParam(
            role="system",
            type="message",
            content=[ResponseInputTextParam(text=system_prompt, type="input_text")],
        ),
        EasyInputMessageParam(
            role="user",
            type="message",
            content=[ResponseInputTextParam(text=user_text, type="input_text")],
        ),
    ]
    chat = await client.responses.create(model="gpt-4o-mini", input=messages)
    return chat.output[0].content[0].text


async def text_to_speech(text: str, output_path: str) -> None:
    speech = await client.audio.speech.create(
        model="gpt-4o-mini-tts", voice="alloy", input=text
    )
    with open(output_path, "wb") as f:
        f.write(speech.read())


async def voice_to_voice(input_audio: str, output_audio: str) -> None:
    print("🎤 Transcribing...")
    text = await transcribe_audio(input_audio)
    print(text)
    print("📨 Getting AI response...")
    answer = await get_ai_response(text)
    print(answer)
    print("🔊 Converting text to speech...")
    await text_to_speech(answer, output_audio)
    print("✅ Done! Audio response saved:", output_audio)


if __name__ == "__main__":
    lang = "uz"
    asyncio.run(voice_to_voice(f"input_voice/{lang}.mp3", f"output_voice/{lang}.mp3"))
