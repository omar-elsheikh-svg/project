from io import BytesIO

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def insights_markdown(insights: dict) -> str:
    metrics = insights.get("general_metrics", {})
    lines = [
        "# Executive Sales Summary",
        "",
        "## Key Performance Indicators",
        f"- Revenue: {metrics.get('total_revenue', 0):,.2f}",
        f"- Orders: {metrics.get('total_orders', 0):,}",
        f"- Average order value: {metrics.get('average_order_value', 0):,.2f}",
    ]
    if "net_profit" in metrics:
        lines += [
            f"- Net profit: {metrics['net_profit']:,.2f}",
            f"- Margin: {metrics.get('profit_margin_percentage', 0):,.2f}%",
        ]
    lines += ["", "## Top Products"]
    for item in insights.get("products_analysis", {}).get("top_5_products", []):
        lines.append(
            f"- {item['product_name']}: {item['revenue_generated']:,.2f} revenue"
        )
    return "\n".join(lines) + "\n"


def insights_pdf(insights: dict) -> bytes:
    buffer = BytesIO()
    document = canvas.Canvas(buffer, pagesize=LETTER)
    y = 750
    for line in insights_markdown(insights).replace("#", "").splitlines():
        document.drawString(54, y, line[:110])
        y -= 16
        if y < 54:
            document.showPage()
            y = 750
    document.save()
    return buffer.getvalue()
