# BRAHMO Clinical AI — Streamlit Community Cloud MVP

**Status:** engineering prototype only. Not for clinical use, not a medical device, and not approved for use with real patients.

## End-to-end pipeline

```
Doctor UI (Streamlit)
    │
    ▼
Session scope (tenant / encounter — demo labels only)
    │
    ├─► Medication-review path
    │       Scribe-style product lines
    │           → Drug identity graph (synthetic catalogue)
    │           → Ingredient expansion
    │           → Deterministic safety rail (8-state contract)
    │           → Doctor review / confirm
    │           → Audit event (Supabase if configured)
    │
    └─► Clinical-reference path
            Question
                → Lexical retrieval over knowledge/ (verified-live demo)
                → Evidence sufficiency + applicability gate
                → Grounded composition (excerpts + citations, no LLM)
                → Doctor review / confirm
                → Audit event
```

### Durable persistence (Supabase)

| Table | Purpose |
|-------|---------|
| `audit_events` | Event log (`event_type`, `event_status`, `details` jsonb, `app_version`) |
| `source_versions` | Source registry (`source_name`, `version_label`, `content_hash`, `status`) |

Without Supabase secrets the app still runs; audit falls back to in-memory (and local SQLite on a developer machine). Local files are **not durable** on Streamlit Community Cloud.

## Supabase setup

1. Create a free project at https://supabase.com
2. Open **SQL Editor** and run `supabase/schema.sql` (matches the schema you provided).
3. **Settings → API**: copy **Project URL** and the **service_role** key (not the anon key). Never commit the service role key or expose it to the browser.
4. Confirm RLS is enabled and `anon` / `authenticated` have no grants on these tables.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub (`main` branch). Root must contain:
   - `app.py`
   - `requirements.txt`
   - `brahmo/`
   - `knowledge/`
   - `.streamlit/config.toml`
   - `supabase/schema.sql`
2. Sign in at https://share.streamlit.io with GitHub.
3. **Create app** → select the repo and `main` → main file path `app.py` → Deploy.
4. In the app **Settings → Secrets**, paste:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

5. Reboot the app. Sidebar should show **Supabase connected**.
6. Run a medication or reference pipeline; rows appear in Supabase **Table Editor → audit_events**.

No secrets are required for the core demo (safety + retrieval). Secrets only enable durable audit / source version registry.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
streamlit run app.py
```

Optional env vars (same names as Streamlit secrets):

```bash
export SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
```

## Safe demonstration

Use only synthetic catalogue brands (`Demo Product A/B/C`) and `TEST_INGREDIENT_*` tokens. Never enter real patient details or use outputs for care decisions.

## What is intentionally not implemented

Real drug master, brand licensing, fixed-dose-combination clinical data, interaction/allergy/pregnancy rules, Indian regulatory event feed, production RAG/LLM, authentication, multi-tenant isolation, encryption at rest for PHI, production audit integrity, offline sync, clinical approvals, or regulatory clearance.

## Before any clinical pilot

- Qualified clinical review of intended use, content, safety rules, and evaluation sets.
- Indian legal/regulatory counsel on medical-device classification, DPDP, and professional rules.
- Documented source rights for access, storage, indexing, display, and training.
- Authenticated access, tenant isolation, data minimization, secure secrets, retention/erasure, incident response.
- Held-out evaluation gates and independent sign-off before enabling clinical capabilities.
