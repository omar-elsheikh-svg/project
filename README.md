# Sales Intelligence SaaS

This project turns CSV/XLSX sales data into dashboard metrics and optional OpenRouter executive reports.

## Architecture

- `project.py`: reusable cleaning, schema mapping, and sales analytics.
- `main.py`: FastAPI API with authentication, upload validation, rate limiting, exports, and billing.
- `app/`: configuration, Supabase authentication/storage access, Stripe, OpenRouter retries and fallback, usage limits, and report exports.
- `streamlit_app.py`: customer portal with login, drag-and-drop upload, Plotly charts, AI reports, and downloads.
- `supabase_schema.sql`: PostgreSQL tables and the atomic monthly usage function.

## Local setup

1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in Supabase, Stripe, and `OPENROUTER_API_KEY`.
3. Run `supabase_schema.sql` in the Supabase SQL editor.
4. Start the API: `uvicorn main:app --reload`
5. Start the portal in another terminal: `streamlit run streamlit_app.py`

The API is documented at `http://localhost:8000/docs`.

## Supabase setup

Enable email/password authentication. Configure a storage bucket if original uploads should be retained; this MVP stores normalized insights in `datasets` and does not retain raw file bytes. Keep `SUPABASE_SERVICE_ROLE_KEY` server-side only.

## Stripe setup

Create a recurring price and place its ID in `STRIPE_PRICE_ID`. Register `/billing/webhook` as a Stripe webhook and set `STRIPE_WEBHOOK_SECRET`. Run Stripe CLI locally with `stripe listen --forward-to localhost:8000/billing/webhook`.

## Security notes

Never commit `.env`. Configure `OPENROUTER_API_KEY` and optionally `OPENROUTER_MODELS` as a comma-separated fallback list. Dataset and report queries always filter by the authenticated user ID, and report quotas are enforced in the database rather than the Streamlit client.

## Tests

Run `pytest -q`. Tests cover the existing analytics logic when those tests are present and the SaaS Markdown/PDF export boundary.