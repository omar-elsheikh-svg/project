import os
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

st.set_page_config(page_title="Sales Intelligence", page_icon="S", layout="wide")
st.title("Sales Intelligence")
st.caption(
    "Upload sales data, understand the numbers, then generate an executive report when it is useful."
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
    columns = st.columns(4)
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

    action_col, export_col = st.columns(2)
    with action_col:
        if st.button("Generate AI executive report"):
            with st.spinner("Generating executive report..."):
                report_response = api_request(
                    "POST", f"/datasets/{dataset['dataset_id']}/ai-report"
                )
            if report_response is not None and report_response.ok:
                st.session_state.report = report_response.json()["report"]
            else:
                st.error(response_error(report_response))
    with export_col:
        markdown_response = api_request(
            "GET", f"/datasets/{dataset['dataset_id']}/markdown"
        )
        pdf_response = api_request("GET", f"/datasets/{dataset['dataset_id']}/pdf")
        st.download_button(
            "Download Markdown", markdown_response.content, "report.md", "text/markdown"
        )
        st.download_button(
            "Download PDF", pdf_response.content, "report.pdf", "application/pdf"
        )

    if "report" in st.session_state:
        st.markdown(st.session_state.report)

if st.sidebar.button("Upgrade to Premium"):
    checkout_response = api_request("POST", "/billing/checkout")
    if checkout_response is not None and checkout_response.ok:
        st.link_button("Continue to Stripe", checkout_response.json()["checkout_url"])
    else:
        st.error(response_error(checkout_response))
