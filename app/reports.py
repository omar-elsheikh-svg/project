from io import BytesIO

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from project import format_executive_summary


def insights_markdown(insights: dict) -> str:
    summary = format_executive_summary(insights, output_file=None).strip()
    return f"# Executive Sales Summary\n\n{summary}\n"


def insights_pdf(insights: dict) -> bytes:
    buffer = BytesIO()
    document = canvas.Canvas(buffer, pagesize=LETTER)
    y = 750
    summary = format_executive_summary(insights, output_file=None)
    for line in summary.splitlines():
        document.drawString(54, y, line[:110])
        y -= 16
        if y < 54:
            document.showPage()
            y = 750
    document.save()
    return buffer.getvalue()
