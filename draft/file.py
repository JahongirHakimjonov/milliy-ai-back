import asyncio

from openai import AsyncOpenAI
from openai.types.responses import EasyInputMessageParam, ResponseInputTextParam

from apps.chat.services.file import (
    save_markdown_to_docx,
    save_markdown_to_pdf_reportlab,
)
from dev import get_openai_client

client: AsyncOpenAI = get_openai_client()


async def generate_markdown(
    prompt_text: str, model: str = "gpt-4o-mini", max_retries: int = 2
) -> str:
    markdown_system_prompt = (
        "Siz professional texnik yozuvchi va mazmun yaratuvchisiz. JAWOBNI FAQAT Markdown formatida chiqaring. "
        "Foydalanish uchun: #, ##, ### sarlavhalar, - yoki * bilan listlar, 1. 2. bilan raqamli ro'yxatlar, "
        "`kod` va ``` blok-kodlarni ishlating. Bo'limlar, qisqacha xulosalar va punktlar qo'shing. "
        "Hech qanday izoh yoki tushuntirish chiqarmang — faqat Markdown."
    )

    messages = [
        EasyInputMessageParam(
            role="system",
            type="message",
            content=[
                ResponseInputTextParam(text=markdown_system_prompt, type="input_text")
            ],
        ),
        EasyInputMessageParam(
            role="user",
            type="message",
            content=[ResponseInputTextParam(text=prompt_text, type="input_text")],
        ),
    ]

    for attempt in range(max_retries + 1):
        try:
            resp = await client.responses.create(model=model, input=messages)
            # response shape may vary; handle safely
            text = ""
            # try common places
            if hasattr(resp, "output") and resp.output:
                # new Responses API returns .output which is list of content objects
                for item in resp.output:
                    # item.content may be list of dicts
                    if hasattr(item, "content") and item.content:
                        for c in item.content:
                            if getattr(c, "text", None):
                                text += c.text
                            elif getattr(c, "type", None) == "output_text" and getattr(
                                c, "text", None
                            ):
                                text += c.text
            if not text:
                # fallback: try str(resp)
                text = str(resp)
            return text.strip()
        except Exception as e:
            last_err = e
            if attempt == max_retries:
                raise
            await asyncio.sleep(1 + attempt * 2)
    raise RuntimeError("OpenAI request failed") from last_err


if __name__ == "__main__":
    PROMPT = """
    Write a detailed 5-page article about "The Future of AI in Software Development".
    Use Markdown format. Include at least:
    - Title and subtitle
    - 4 major sections with headings (use ##)
    - bullet lists and numbered lists where appropriate
    - at least one fenced code block example
    - a short conclusion and recommended next steps
    """

    async def main():
        md = await generate_markdown(PROMPT)
        # Save DOCX
        save_markdown_to_docx(md, "ai_future_beautiful.docx")
        # Save PDF with ReportLab renderer
        save_markdown_to_pdf_reportlab(md, "ai_future_reportlab.pdf")

    asyncio.run(main())
