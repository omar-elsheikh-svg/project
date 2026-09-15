import asyncio

from app.ai_service import generate_executive_report


def LLM_report(insights: dict) -> str:
    """Compatibility wrapper that uses the configured OpenRouter client."""
    return asyncio.run(generate_executive_report(insights))


if __name__ == "__main__":
    raise SystemExit(
        "Use POST /datasets/{dataset_id}/ai-report from the application instead."
    )
