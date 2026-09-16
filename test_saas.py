from app import limits
from app import ai_service
from app.reports import insights_markdown, insights_pdf
from project import format_executive_summary


def test_markdown_export_contains_metrics():
    result = insights_markdown(
        {
            "general_metrics": {
                "total_revenue": 123.5,
                "total_orders": 2,
                "average_order_value": 61.75,
            }
        }
    )
    assert "123.50" in result
    assert "# Executive Sales Summary" in result


def test_pdf_export_is_valid_pdf():
    result = insights_pdf(
        {
            "general_metrics": {
                "total_revenue": 10,
                "total_orders": 1,
                "average_order_value": 10,
            }
        }
    )
    assert result.startswith(b"%PDF")


def test_exports_use_formatted_executive_summary():
    insights = {
        "general_metrics": {
            "total_revenue": 123.5,
            "total_orders": 2,
            "average_order_value": 61.75,
        },
        "products_analysis": {
            "top_5_products": [],
            "dead_stock_candidates": [],
        },
    }

    summary = format_executive_summary(insights, output_file=None)
    exported = insights_markdown(insights)

    assert "EXECUTIVE SALES SUMMARY" in summary
    assert summary.strip() in exported


def test_ai_report_prompt_uses_summary_and_strategic_sections(monkeypatch):
    captured = []

    async def fake_generate_text(prompt, attempts=2):
        captured.append(prompt)
        return "report"

    monkeypatch.setattr(ai_service, "generate_text", fake_generate_text)

    import asyncio

    asyncio.run(
        ai_service.generate_executive_report(
            {
                "general_metrics": {
                    "total_revenue": 123.5,
                    "total_orders": 2,
                    "average_order_value": 61.75,
                }
            }
        )
    )

    prompt = captured[0]
    assert "Verified sales summary:" in prompt
    assert '"general_metrics"' not in prompt
    assert "CFO Performance Diagnosis" in prompt
    assert "30-Day Action Plan" in prompt


def test_missing_profile_is_provisioned(monkeypatch):
    class Query:
        def __init__(self, data=None):
            self.data = data

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def maybe_single(self):
            return self

        def upsert(self, payload):
            self.payload = payload
            return self

        def execute(self):
            return self

    class Supabase:
        def __init__(self):
            self.profile_query = Query()

        def table(self, name):
            assert name == "profiles"
            return self.profile_query

    client = Supabase()
    monkeypatch.setattr(limits, "get_supabase", lambda: client)
    limits.ensure_report_allowed("user-id")
    assert client.profile_query.payload == {"id": "user-id"}


def test_free_profile_is_blocked_from_premium_features(monkeypatch):
    class Query:
        data = {"plan": "free"}

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def maybe_single(self):
            return self

        def execute(self):
            return self

    class Supabase:
        def table(self, name):
            assert name == "profiles"
            return Query()

    monkeypatch.setattr(limits, "get_supabase", lambda: Supabase())
    import pytest

    with pytest.raises(Exception) as error:
        limits.ensure_premium("user-id")
    assert error.value.status_code == 402


def test_openrouter_falls_back_to_next_model(monkeypatch):
    class Response:
        choices = [
            type(
                "Choice",
                (),
                {"message": type("Message", (), {"content": "fallback report"})()},
            )()
        ]

    class Completions:
        def __init__(self):
            self.models = []

        async def create(self, **kwargs):
            self.models.append(kwargs["model"])
            if len(self.models) == 1:
                raise RuntimeError("rate limited")
            return Response()

    class Client:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": Completions()})()

        async def close(self):
            pass

    client = Client()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "_client", lambda: client)
    monkeypatch.setattr(ai_service, "_models", lambda: ("primary", "secondary"))
    monkeypatch.setattr(ai_service, "_is_retryable", lambda error: False)

    import asyncio

    result = asyncio.run(ai_service.generate_text("hello", attempts=1))
    assert result == "fallback report"
    assert client.chat.completions.models == ["primary", "secondary"]
