"""Reliable OpenRouter access for executive reports.

OpenRouter and free model availability are external dependencies, so no client
can guarantee 100% uptime. This module bounds each request, retries transient
failures, and tries the next configured model before returning an error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Iterable, Mapping

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODELS = (
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_TOKENS = 2000


class AIServiceError(RuntimeError):
    """Raised when all configured OpenRouter models fail."""


def _models() -> tuple[str, ...]:
    configured = os.getenv("OPENROUTER_MODELS", "")
    models = tuple(model.strip() for model in configured.split(",") if model.strip())
    return models or DEFAULT_MODELS


def _client() -> AsyncOpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise AIServiceError("OPENROUTER_API_KEY is not configured")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        default_headers={
            "HTTP-Referer": os.getenv(
                "OPENROUTER_HTTP_REFERER", "http://localhost:8501"
            ),
            "X-Title": os.getenv("OPENROUTER_X_TITLE", "Free SaaS App"),
        },
        timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        max_retries=0,
    )


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return True
    return isinstance(error, APIStatusError) and error.status_code in {
        408,
        409,
        429,
        500,
        502,
        503,
        504,
    }


def _messages(
    prompt_or_messages: str | Iterable[Mapping[str, str]],
) -> list[dict[str, str]]:
    if isinstance(prompt_or_messages, str):
        return [{"role": "user", "content": prompt_or_messages}]
    return [dict(message) for message in prompt_or_messages]


async def _complete(
    client: AsyncOpenAI,
    messages: list[dict[str, str]],
    *,
    stream: bool = False,
    attempts: int = 2,
) -> AsyncIterator[str] | str:
    last_error: Exception | None = None
    for model in _models():
        for attempt in range(max(1, attempts)):
            try:
                logger.info(
                    "Requesting OpenRouter model %s (attempt %d)",
                    model,
                    attempt + 1,
                )
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    stream=stream,
                )
                if stream:

                    async def chunks() -> AsyncIterator[str]:
                        async for chunk in response:
                            text = (
                                chunk.choices[0].delta.content
                                if chunk.choices
                                else None
                            )
                            if text:
                                yield text

                    return chunks()
                text = response.choices[0].message.content if response.choices else None
                if text:
                    logger.info("OpenRouter model %s responded successfully", model)
                    return text
                raise AIServiceError(
                    f"OpenRouter model {model} returned an empty response"
                )
            except Exception as error:
                last_error = error
                if isinstance(error, APIStatusError) and error.status_code in {
                    401,
                    403,
                }:
                    raise AIServiceError("OpenRouter authentication failed") from error
                if not _is_retryable(error):
                    logger.warning(
                        "OpenRouter model %s failed without retry: %s", model, error
                    )
                    break
                logger.warning(
                    "OpenRouter model %s failed; retrying or falling back: %s",
                    model,
                    error,
                )
                if attempt + 1 < max(1, attempts):
                    await asyncio.sleep(2**attempt)
    raise AIServiceError(
        "All OpenRouter models are temporarily unavailable"
    ) from last_error


async def generate_text(
    prompt_or_messages: str | Iterable[Mapping[str, str]], attempts: int = 2
) -> str:
    """Generate text using retries and model fallback."""
    client = _client()
    try:
        result = await _complete(
            client, _messages(prompt_or_messages), attempts=attempts
        )
        return (
            result
            if isinstance(result, str)
            else "".join([part async for part in result])
        )
    finally:
        await client.close()


async def stream_text(
    prompt_or_messages: str | Iterable[Mapping[str, str]], attempts: int = 2
) -> AsyncIterator[str]:
    """Yield response text chunks for Streamlit or another async consumer."""
    client = _client()
    try:
        result = await _complete(
            client, _messages(prompt_or_messages), stream=True, attempts=attempts
        )
        if isinstance(result, str):
            yield result
            return
        async for part in result:
            yield part
    finally:
        await client.close()


async def generate_executive_report(insights: dict, attempts: int = 2) -> str:
    prompt = f"""You are an expert Chief Commercial Officer (CCO) and Retail Data Analyst.
Your task is to generate a comprehensive, executive-level sales performance report based on the provided JSON data.

STRICT RULES & CONSTRAINTS:
1. BILINGUAL ACCURACY:
   - Write product names with their exact original names provided in the dataset. If providing bilingual titles, ensure accurate context-aware translations (e.g., do not translate "فستان صيفي مشجر" to "Sequined Dress").
   - Maintain professional business Arabic/English terminology.

2. LOGICAL CONSISTENCY:
   - A top-selling product by revenue or volume MUST NEVER be listed as a "Dead Stock" or "Slow-moving item".
   - Ensure numbers, order counts, and percentages match the input data precisely.

3. REPORT STRUCTURE (Markdown Output):
   Structure your report cleanly with the following headers:

   # 📊 Executive Sales Report

   ## 1. Core KPIs & Financial Summary
   - Highlight Total Revenue, Net Profit, Profit Margin, Orders Count, Average Order Value (AOV), and Basket Mix (% Multi-item vs Single-item).

   ## 2. Top Performers & Revenue Drivers
   - Provide a clean markdown table of Top 5 products with Units Sold, Revenue Generated, and Average Price per Unit.
   - Include a short executive commentary on what drives high revenue.

   ## 3. Inventory Health & Stagnation Risk
   - List genuinely low-performing or slow-moving items (excluding top performers).
   - Provide concrete, actionable recommendations (e.g., bundling, discount clearances, targeted marketing).

   ## 4. Cross-Selling & Basket Optimization
   - Present top product pairs frequently bought together.
   - Suggest bundle strategies to raise Average Order Value (AOV).

   ## 5. Peak Demand & Operational Insights
   - Highlight peak purchasing hours (format as HH:MM, e.g., 17:00) and peak days.
   - Recommend optimal staffing or ad-campaign scheduling times based on these peak hours.

   ## 6. Strategic Action Plan (Next 30 Days)
   - 3-4 bullet points with high-impact, prioritized steps for store owners.

4. FORMATTING:
   - Use clean Markdown tables, bold key figures, and use bullet points for readability.
   - Ensure time formatting is clean (e.g., 17:00, not 17 :00).

Insights JSON:
{json.dumps(insights, default=str)}
"""
    return await generate_text(prompt, attempts=attempts)
