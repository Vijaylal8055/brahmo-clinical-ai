"""
BRAHMO Clinical AI — Streamlit Community Cloud MVP (end-to-end pipeline)

Status: engineering prototype only.
Not for clinical use. Not a medical device. Not approved for real patients.
Do not enter real patient data.
"""

from __future__ import annotations

import streamlit as st

from brahmo.safety import VALID_STATES, COVERAGE_MANIFEST, RULE_VERSION
from brahmo.drug_graph import MAPPING_VERSION, DRUG_CATALOGUE
from brahmo.orchestrator import (
    run_medication_review_pipeline,
    run_reference_pipeline,
)
from brahmo.audit import (
    write_audit_event,
    recent_audit_events,
    supabase_configured,
    register_source_version,
    list_source_versions,
)
from brahmo import __version__


def _diagnose_supabase() -> dict:
    """Self-contained Supabase check (does not depend on brahmo/audit.py changes)."""
    import base64, json as _json, os
    rep: dict = {}
    url = key = None
    try:
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase_url")
        key = (
            st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
            or st.secrets.get("SUPABASE_KEY")
            or st.secrets.get("supabase_service_role_key")
        )
    except Exception as exc:
        rep["secrets_error"] = f"{type(exc).__name__}: {exc}"
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    rep["url_present"] = bool(url)
    rep["key_present"] = bool(key)
    if not url or not key:
        return rep
    url, key = str(url).strip(), str(key).strip()
    rep["url_host"] = url.replace("https://", "").split("/")[0]
    rep["url_looks_ok"] = url.startswith("https://") and ".supabase.co" in url
    if key.startswith("sb_secret_"):
        rep["key_type"] = "new-style secret key (sb_secret_...)"
    elif key.startswith("sb_publishable_"):
        rep["key_type"] = "PUBLISHABLE key - WRONG, need secret/service_role"
    else:
        try:
            seg = key.split(".")[1]
            seg += "=" * (-len(seg) % 4)
            rep["key_type"] = "legacy JWT, role=" + str(
                _json.loads(base64.urlsafe_b64decode(seg)).get("role")
            )
        except Exception:
            rep["key_type"] = "unrecognised format"
    try:
        import supabase as _sb
        rep["supabase_py_version"] = getattr(_sb, "__version__", "unknown")
    except Exception as exc:
        rep["supabase_import_error"] = f"{type(exc).__name__}: {exc}"
        return rep
    try:
        from supabase import create_client
        client = create_client(url, key)
        rep["client_created"] = True
    except Exception as exc:
        rep["client_error"] = f"{type(exc).__name__}: {exc}"[:400]
        return rep
    try:
        client.table("audit_events").insert(
            {"event_type": "diagnostic_ping", "event_status": "OK",
             "details": {"prototype": True}, "app_version": __version__}
        ).execute()
        rep["insert_ok"] = True
    except Exception as exc:
        rep["insert_error"] = f"{type(exc).__name__}: {exc}"[:600]
    try:
        client.table("source_versions").upsert(
            {"source_name": "diagnostic_ping", "version_label": "0", "status": "DRAFT"},
            on_conflict="source_name,version_label",
        ).execute()
        rep["source_versions_upsert_ok"] = True
    except Exception as exc:
        rep["source_versions_error"] = f"{type(exc).__name__}: {exc}"[:600]
    return rep


st.set_page_config(
    page_title="BRAHMO Clinical AI (Demo)",
    page_icon="🩺",
    layout="wide",
)

st.title("BRAHMO Clinical AI — Doctor-facing demo")
st.caption(f"Prototype v{__version__} · Streamlit Community Cloud · Not for clinical use")

st.error(
    "**Safety notice.** This application is an engineering prototype. "
    "It is **not** clinically validated, **not** a medical device, and **not** approved "
    "for use with real patients. Do not enter identifiable patient data. "
    "Outputs must not guide diagnosis, prescribing, or care decisions."
)

with st.expander("Architecture alignment (read once)", expanded=False):
    st.markdown(
        """
This demo implements a **thin slice** of the architecture:

| Stage | Demo behaviour |
|-------|----------------|
| Identity / tenant | Synthetic tenant label only (no real auth) |
| Intent router | Keyword classifier → medication review **or** clinical reference |
| Drug identity graph | Small synthetic catalogue; ambiguity stays unresolved |
| Deterministic safety rail | Eight-state contract; duplicate-token demo rule only |
| Hybrid retrieval | Local lexical search over fictional `knowledge/` files |
| Evidence sufficiency gate | Blocks composition when no applicable verified-live chunk |
| Grounded composition | Deterministic excerpts + citations (no LLM required) |
| Doctor approval boundary | UI shows draft vs confirmed; no autonomous export |
| Audit | Supabase when configured; else in-memory / local SQLite |

**Not implemented:** real drug master, interaction/allergy rules, Indian regulatory
event feed, production RAG/LLM, authentication, tenant isolation, encryption,
clinical approvals, or regulatory clearance.
"""
    )

with st.sidebar:
    st.header("Session scope (demo)")
    tenant_id = st.text_input("Tenant ID", value="demo-tenant-001")
    encounter_ref = st.text_input("Encounter ref (pseudonymous)", value="enc-demo-001")
    population = st.selectbox(
        "Population filter (reference path)", ["adult", "pediatric", "unspecified"]
    )
    st.divider()
    st.markdown("**Versions**")
    st.code(f"drug map: {MAPPING_VERSION}\nrules: {RULE_VERSION}", language=None)
    st.divider()
    st.markdown("**Persistence**")
    if supabase_configured():
        st.success("Supabase connected (durable audit)")
    else:
        st.warning(
            "Supabase not configured. Audit uses in-memory / local SQLite only "
            "(not durable on Community Cloud). Add secrets to enable."
        )
    if st.button("Test Supabase write"):
        st.json(_diagnose_supabase())
    if st.button("Test audit logger path"):
        import brahmo.audit as _audit
        _eid = write_audit_event("logger_path_test", {"note": "sidebar test"}, event_status="OK")
        _rec = next((r for r in reversed(_audit._MEMORY_EVENTS) if r["id"] == _eid), {})
        _client = _audit._get_supabase()
        st.json(
            {
                "event_id": _eid,
                "audit_module_file": getattr(_audit, "__file__", "?"),
                "has_new_cache_fix": hasattr(_audit, "_supabase_cache_key"),
                "audit_client_created": _client is not None,
                "supabase_error": _rec.get("payload", {}).get("_supabase_error", "none recorded"),
            }
        )
    st.caption("Do not store PHI in audit payloads.")

tab_pipeline, tab_meds, tab_ref, tab_states, tab_audit = st.tabs(
    [
        "1 · End-to-end pipeline",
        "2 · Medication review",
        "3 · Clinical reference",
        "4 · Eight states & coverage",
        "5 · Audit & sources",
    ]
)

with tab_pipeline:
    st.subheader("End-to-end doctor path (demo)")
    st.markdown(
        """
1. Establish scope (sidebar tenant / encounter)  
2. Enter a **reference question** *or* synthetic **medication lines**  
3. Router chooses the path  
4. Structured drug resolution + deterministic checks **or** retrieval + sufficiency + citations  
5. Review the draft; optionally mark doctor-confirmed (session only)
"""
    )

    mode = st.radio(
        "Input mode",
        ["Clinical reference question", "Medication review (product lines)"],
        horizontal=True,
    )

    if mode.startswith("Clinical"):
        q = st.text_input(
            "Question",
            value="What does the current demo workflow say about the assessment section?",
        )
        if st.button("Run reference pipeline", type="primary", key="e2e_ref"):
            pop = None if population == "unspecified" else population
            result = run_reference_pipeline(q, population=pop, tenant_id=tenant_id)
            st.session_state["last_result"] = result
    else:
        default_lines = "Demo Product A\nDemo Product B\nDemo Product C"
        raw = st.text_area(
            "Product lines (brand string, or `name | ingredient, ingredient`)",
            value=default_lines,
            height=120,
        )
        if st.button("Run medication pipeline", type="primary", key="e2e_med"):
            lines = [ln for ln in raw.splitlines() if ln.strip()]
            result = run_medication_review_pipeline(
                lines, tenant_id=tenant_id, encounter_ref=encounter_ref
            )
            st.session_state["last_result"] = result

    result = st.session_state.get("last_result")
    if result:
        st.markdown(f"**Pipeline:** `{result.get('pipeline')}`")
        if result.get("pipeline") == "clinical_reference":
            gate = result.get("gate", {})
            if result.get("abstained"):
                st.warning(result.get("answer"))
            else:
                st.success("Grounded demo answer (excerpts only)")
                st.markdown(result.get("answer", ""))
            st.markdown("#### Sufficiency gate")
            st.json(gate)
            if result.get("citations"):
                st.markdown("#### Citations")
                for c in result["citations"]:
                    with st.container(border=True):
                        st.markdown(
                            f"**{c.get('title')}** — {c.get('issuer')} · "
                            f"ed. {c.get('edition')} · effective {c.get('effective_from')}"
                        )
                        st.caption(
                            f"{c.get('filename')} lines {c.get('line_start')}–{c.get('line_end')} · "
                            f"section “{c.get('heading')}”"
                        )
                        st.write(c.get("excerpt"))
        else:
            st.markdown("#### Drug resolution")
            for r in result.get("resolutions", []):
                with st.container(border=True):
                    st.markdown(f"**{r.get('query')}** → `{r.get('state')}`")
                    st.write(r.get("message"))
                    if r.get("candidates"):
                        st.json(r["candidates"])
                    if r.get("ingredients"):
                        st.json(r["ingredients"])
            st.markdown("#### Safety checks (deterministic)")
            for c in result.get("checks", []):
                status = c["status"]
                icon = (
                    "🔴"
                    if status in (
                        "HIT", "UNVERIFIED_INPUT", "PARTIAL_COVERAGE",
                        "SERVICE_UNAVAILABLE", "SOURCE_CONFLICT", "DATA_EXPIRED",
                    )
                    else "🟡" if status == "NOT_CHECKED" else "🟢"
                )
                with st.container(border=True):
                    st.markdown(f"{icon} **{c['check']}** — `{status}`")
                    st.write(c["message"])
                    if c.get("details"):
                        st.json(c["details"])
            st.info(result.get("notice", ""))

        confirmed = st.checkbox(
            "Doctor confirms this draft (session only — not a legal signature)",
            key="confirm_box",
        )
        if confirmed:
            write_audit_event(
                "doctor_confirmation_demo",
                {
                    "tenant_id": tenant_id,
                    "encounter_ref": encounter_ref,
                    "pipeline": result.get("pipeline"),
                    "note": "Session checkbox only; not a production approval record",
                },
                event_status="CONFIRMED",
            )
            st.success("Confirmation recorded in audit.")

with tab_meds:
    st.subheader("Medication-review path")
    st.markdown(
        "Enter synthetic product strings. Ambiguous brands (e.g. **Demo Product C**) "
        "remain unresolved. Duplicate ingredient tokens produce a `HIT` on the demo rule only."
    )
    st.markdown("**Catalogue brands (synthetic):**")
    st.code(
        "\n".join(
            f"{v['brand']} → {[i['name'] for i in v['ingredients']]}"
            for v in DRUG_CATALOGUE.values()
        ),
        language=None,
    )
    example = "Demo Product A\nDemo Product B\nDemo Product C"
    raw = st.text_area("Product lines", value=example, height=120, key="med_tab_raw")
    if st.button("Resolve & check", key="med_tab_btn"):
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        out = run_medication_review_pipeline(
            lines, tenant_id=tenant_id, encounter_ref=encounter_ref
        )
        for r in out["resolutions"]:
            st.write(f"**{r['query']}** → `{r['state']}` — {r['message']}")
        for c in out["checks"]:
            st.write(f"`{c['status']}` · {c['check']}: {c['message']}")

with tab_ref:
    st.subheader("Clinical reference path")
    st.markdown(
        "Ask about the **assessment section**, **versioning**, or **eligibility** "
        "in the fictional demo corpus. Pediatric filter will abstain on adult-only sources."
    )
    q2 = st.text_input(
        "Reference question", value="assessment section required elements", key="ref_q"
    )
    if st.button("Retrieve & gate", key="ref_btn"):
        pop = None if population == "unspecified" else population
        out = run_reference_pipeline(q2, population=pop, tenant_id=tenant_id)
        st.markdown(out["answer"])
        st.json(
            {
                "gate": out["gate"],
                "evidence_count": out["evidence_count"],
                "abstained": out["abstained"],
            }
        )

with tab_states:
    st.subheader("Eight-state safety contract")
    st.write(
        "Every medication check returns **exactly one** of these states. "
        "Missing coverage is never rendered as safe."
    )
    cols = st.columns(4)
    for i, state in enumerate(VALID_STATES):
        cols[i % 4].code(state, language=None)
    st.subheader("Rule coverage manifest (honest disclosure)")
    st.json(COVERAGE_MANIFEST)
    st.caption(
        f"Rule version `{RULE_VERSION}`. Unsupported checks return `NOT_CHECKED` "
        "or contribute to `PARTIAL_COVERAGE` — never a silent all-clear."
    )

with tab_audit:
    st.subheader("Audit events")
    if supabase_configured():
        st.success("Reading from Supabase `audit_events` (durable).")
    else:
        st.warning(
            "Supabase not configured. Showing in-memory / local events only. "
            "On Community Cloud these are lost on restart unless you add secrets."
        )

    events = recent_audit_events(limit=30)
    if events:
        st.dataframe(events, width="stretch", hide_index=True)
    else:
        st.caption("No audit events yet — run a pipeline first.")

    st.divider()
    st.subheader("Source versions registry")
    st.caption(
        "Maps to Supabase `source_versions`. Demo corpus rows can be registered below."
    )
    col_a, col_b = st.columns(2)
    with col_a:
        src_name = st.text_input("source_name", value="demo_assessment_workflow.md")
        ver_label = st.text_input("version_label", value="1")
    with col_b:
        src_status = st.selectbox("status", ["DRAFT", "verified-live", "withdrawn"])
        content_hash = st.text_input("content_hash (optional)", value="")
    if st.button("Register source version"):
        if not supabase_configured():
            st.error("Supabase not configured — cannot write source_versions.")
        else:
            ok = register_source_version(
                src_name,
                ver_label,
                content_hash=content_hash or None,
                status=src_status,
            )
            if ok:
                st.success("Registered.")
                write_audit_event(
                    "source_version_registered",
                    {"source_name": src_name, "version_label": ver_label, "status": src_status},
                    event_status="OK",
                )
            else:
                st.error("Registration failed (check service role key and RLS).")
                st.json(_diagnose_supabase())

    versions = list_source_versions(limit=20)
    if versions:
        st.dataframe(versions, width="stretch", hide_index=True)
    elif supabase_configured():
        st.caption("No source_versions rows yet.")

st.divider()
st.caption(
    "BRAHMO Clinical AI prototype · Not for clinical use · No real patient data"
)
