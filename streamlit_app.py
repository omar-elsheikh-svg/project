import os
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).with_name(".env"), override=False)

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()

st.set_page_config(page_title="FinExpert", page_icon="F", layout="wide")
st.title("FinExpert")
st.caption(
    "Upload sales data, understand the numbers, then generate an executive report when it is useful."
)
st.markdown(
    """
    <style>
    .premium-blur {
        filter: blur(5px);
        opacity: 0.62;
        user-select: none;
        pointer-events: none;
        max-height: 110px;
        overflow: hidden;
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
        background: rgba(128, 128, 128, 0.08);
    }
    .teaser-copy { color: #a8b3c2; margin: 0.35rem 0 0.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def supabase_client():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in .env."
        )
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def api_request(method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    try:
        return requests.request(
            method, f"{API_URL}{path}", headers=headers, timeout=120, **kwargs
        )
    except requests.RequestException as exc:
        st.error(f"Cannot reach the API at {API_URL}: {exc}")
        return None


def response_error(response) -> str:
    """Read FastAPI JSON errors and plain-text proxy/server errors safely."""
    if response is None:
        return "The API request did not complete."
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("detail") or body.get("message") or body)
        return str(body)
    except ValueError:
        text = response.text.strip()
        return text or f"API request failed with HTTP {response.status_code}."


def sync_user_profile() -> None:
    """Refresh the plan on every Streamlit rerun without caching the response."""
    response = api_request("GET", "/me")
    if response is not None and response.ok:
        profile = response.json()
        plan = str(profile.get("plan", profile.get("tier", "free"))).lower()
        st.session_state.user_profile = {**profile, "plan": plan, "tier": plan}
        return

    # A stale premium flag must never keep premium UI enabled after a failed sync.
    st.session_state.user_profile = {"plan": "free", "tier": "free"}
    if response is not None and response.status_code == 401:
        st.session_state.clear()
        st.rerun()
    st.warning(
        "Your plan could not be refreshed. Premium features are temporarily locked."
    )


def is_premium() -> bool:
    profile = st.session_state.get("user_profile", {})
    return str(profile.get("plan", profile.get("tier", "free"))).lower() == "premium"


def render_upgrade_cta(key: str) -> None:
    if st.button(
        "🔒 Unlock Full Growth Strategy for only $4.99/mo. Stop guessing your marketing. Get actionable cross-selling & peak hour data instantly!",
        key=key,
        type="primary",
    ):
        checkout_response = api_request("POST", "/billing/checkout")
        if checkout_response is not None and checkout_response.ok:
            st.link_button(
                "Continue to secure Stripe checkout",
                checkout_response.json()["checkout_url"],
            )
        else:
            st.error(response_error(checkout_response))


def teaser_table(rows: list[dict], columns: list[str], key: str) -> None:
    visible = rows[:2]
    if visible:
        st.dataframe(pd.DataFrame(visible), hide_index=True, width="stretch")
    hidden = rows[2:]
    if hidden:
        cells = "".join(
            f"<tr>{''.join(f'<td>{escape(str(row.get(column, "")))}</td>' for column in columns)}</tr>"
            for row in hidden
        )
        headers = "".join(
            f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in columns
        )
        st.markdown(
            f'<div class="premium-blur"><table><thead><tr>{headers}</tr></thead><tbody>{cells}</tbody></table></div>',
            unsafe_allow_html=True,
        )
    elif rows:
        st.markdown(
            '<div class="premium-blur">More growth opportunities are available in Premium.</div>',
            unsafe_allow_html=True,
        )
    render_upgrade_cta(key)


if "access_token" not in st.session_state:
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        login = st.form_submit_button("Log in")
    with st.expander("Create an account"):
        with st.form("signup"):
            signup_email = st.text_input("Signup email")
            signup_password = st.text_input("Signup password", type="password")
            signup = st.form_submit_button("Sign up")
        if signup:
            try:
                supabase_client().auth.sign_up(
                    {"email": signup_email, "password": signup_password}
                )
                st.success(
                    "Account created. Check your email if confirmation is enabled."
                )
            except Exception as exc:
                st.error(f"Signup failed: {exc}")
        with st.expander("Reset password"):
            reset_email = st.text_input("Account email", key="reset_email")
            if st.button("Send reset email"):
                try:
                    supabase_client().auth.reset_password_for_email(reset_email)
                    st.success("Password reset email sent if the account exists.")
                except Exception as exc:
                    st.error(f"Could not send reset email: {exc}")
    if login:
        try:
            session = supabase_client().auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            st.session_state.access_token = session.session.access_token
            st.rerun()
        except Exception as exc:
            st.error(f"Login failed: {exc}")
    st.stop()

sync_user_profile()

if st.sidebar.button("Log out"):
    st.session_state.clear()
    st.rerun()

uploaded = st.file_uploader("Upload CSV or XLSX", type=["csv", "xlsx"])
if uploaded:
    if st.button("Analyze dataset", type="primary"):
        response = api_request(
            "POST",
            "/datasets/analyze",
            files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
        )
        if response is not None and response.ok:
            st.session_state.dataset = response.json()
        else:
            st.error(response_error(response))

if "dataset" in st.session_state:
    dataset = st.session_state.dataset
    insights = dataset["insights"]
    metrics = insights.get("general_metrics", {})
    columns = st.columns(5)
    columns[0].metric("Revenue", f"{metrics.get('total_revenue', 0):,.2f}")
    columns[1].metric("Orders", f"{metrics.get('total_orders', 0):,}")
    columns[2].metric("Average order", f"{metrics.get('average_order_value', 0):,.2f}")
    columns[3].metric(
        "Margin",
        (
            f"{metrics.get('profit_margin_percentage', 0):,.2f}%"
            if "profit_margin_percentage" in metrics
            else "N/A"
        ),
    )
    basket = insights.get("basket_size_analysis", {})
    columns[4].metric(
        "Multi-item orders",
        f"{basket.get('multi_item_percentage', 0):,.1f}%",
        help="Orders containing more than one product line.",
    )
    st.caption(
        f"Basket mix: {basket.get('single_item_percentage', 0):,.1f}% single-item orders · "
        f"{basket.get('multi_item_percentage', 0):,.1f}% multi-item orders"
    )

    time_analysis = insights.get("time_analysis") or {}
    peak_hour = time_analysis.get("peak_hour_24h_format")
    peak_day = time_analysis.get("peak_day_of_week", "N/A")
    if peak_hour is not None:
        st.subheader("When customers buy")
        st.info(f"Peak demand: {int(peak_hour):02d}:00 on {peak_day}")
        hourly = pd.DataFrame(time_analysis.get("hourly_order_counts", []))
        if not hourly.empty:
            st.plotly_chart(
                px.imshow(
                    [hourly["orders"].tolist()],
                    x=[f"{hour:02d}:00" for hour in hourly["hour"]],
                    y=["Orders"],
                    labels={"x": "Hour of day", "color": "Orders"},
                    color_continuous_scale="Blues",
                    aspect="auto",
                ),
                width="stretch",
            )

    top_products = pd.DataFrame(
        insights.get("products_analysis", {}).get("top_5_products", [])
    )
    if not top_products.empty:
        st.plotly_chart(
            px.bar(
                top_products,
                x="product_name",
                y="revenue_generated",
                title="Top products by revenue",
            ),
            use_container_width=True,
        )

    st.subheader("Growth opportunities")
    cross_sell = insights.get("cross_selling_opportunities", [])
    dead_stock = insights.get("products_analysis", {}).get("dead_stock_candidates", [])
    insight_col, stock_col = st.columns(2)
    with insight_col:
        st.markdown("#### Cross-selling opportunities")
        teaser_table(
            cross_sell,
            ["product_1", "product_2", "times_bought_together"],
            "upgrade_cross_sell",
        )
    with stock_col:
        st.markdown("#### Slow-moving inventory")
        teaser_table(
            dead_stock,
            ["product_name", "units_sold", "revenue_generated"],
            "upgrade_dead_stock",
        )

    st.subheader("AI executive report")
    if is_premium():
        if st.button("Generate AI executive report"):
            with st.spinner("Generating executive report..."):
                report_response = api_request(
                    "POST", f"/datasets/{dataset['dataset_id']}/ai-report"
                )
            if report_response is not None and report_response.ok:
                st.session_state.report = report_response.json()["report"]
            else:
                st.error(response_error(report_response))
        if "report" in st.session_state:
            st.markdown(st.session_state.report)
    else:
        st.markdown(
            f"Preview: Your store generated **{metrics.get('total_revenue', 0):,.2f}** in revenue across **{metrics.get('total_orders', 0):,}** orders."
        )
        st.markdown(
            f'<div class="premium-blur">Peak demand is {escape(str(peak_day))} at {escape(str(peak_hour or "your busiest hour"))}:00. The full report includes campaign actions, product pair recommendations, and inventory priorities.</div>',
            unsafe_allow_html=True,
        )
        render_upgrade_cta("upgrade_report")

    export_col = st.container()
    with export_col:
        st.markdown("#### Professional exports")
        if is_premium():
            markdown_response = api_request(
                "GET", f"/datasets/{dataset['dataset_id']}/markdown"
            )
            pdf_response = api_request("GET", f"/datasets/{dataset['dataset_id']}/pdf")
            if markdown_response is not None and markdown_response.ok:
                st.download_button(
                    "Download Professional Markdown",
                    markdown_response.content,
                    "report.md",
                    "text/markdown",
                )
            if pdf_response is not None and pdf_response.ok:
                st.download_button(
                    "Download Professional PDF",
                    pdf_response.content,
                    "report.pdf",
                    "application/pdf",
                )
        else:
            st.download_button(
                "Download Professional Markdown (Premium)",
                b"",
                disabled=True,
                key="locked_markdown",
            )
            st.download_button(
                "Download Professional PDF (Premium)",
                b"",
                disabled=True,
                key="locked_pdf",
            )
            render_upgrade_cta("upgrade_exports")

with st.sidebar:
    st.caption("Premium Plan" if is_premium() else "Free Plan")
    if not is_premium():
        render_upgrade_cta("upgrade_sidebar")
