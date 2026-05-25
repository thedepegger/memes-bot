from openai import AsyncOpenAI

from config.settings import settings


llm_client = AsyncOpenAI(
    api_key=settings.OPENROUTER_API_KEY or "set-OPENROUTER_API_KEY-in-env",
    base_url=settings.OPENROUTER_BASE_URL,
    default_headers={
        "HTTP-Referer": settings.OPENROUTER_APP_URL,
        "X-Title": settings.OPENROUTER_APP_NAME,
    },
)


async def call_llm(
    system: str,
    user: str,
    max_tokens: int = 500,
    temperature: float = 0.8,
) -> str:
    response = await llm_client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""
