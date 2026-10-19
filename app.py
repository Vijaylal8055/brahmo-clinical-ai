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
from brahmo.__version__ import APP_VERSION


st.set_page_config(
    page_title="BRAHMO Clinical AI (Demo)",
    page_icon="🩺",
    layout="wide",
)

st.title("BRAHMO Clinical AI — Doctor-facing demo")
st.caption(
    f"Prototype v{APP_VERSION} · Streamlit Community Cloud · Not for clinical use"
)

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
    encounter_ref = st.text_input(
        "Encounter ref (pseudonymous)", value="enc-demo-001"
    )
    population = st.selectbox(
        "Population filter (reference path)",
        ["adult", "pediatric", "unspecified"],
    )

    st.divider()
    st.markdown("**Versions**")
    st.code(
        f"app: {APP_VERSION}\ndrug map: {MAPPING_VERSION}\nrules: {RULE_VERSION}",
        language=None,
    )

    st.divider()
    st.markdown("**Persistence**")

    if supabase_configured():
        st.success("Supabase connected (durable audit)")
    else:
        st.warning(
            "Supabase not configured. Audit uses in-memory / local SQLite only "
            "(not durable on Community Cloud). Add secrets to enable."
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
            value=(
                "What does the current demo workflow say about "
                "the assessment section?"
            ),
        )

        if st.button("Run reference pipeline", type="primary", key="e2e_ref"):
            pop = None if population == "unspecified" else population

            result = run_reference_pipeline(
                q,
                population=pop,
                tenant_id=tenant_id,
            )
            st.session_state["last_result"] = result

    else:
        default_lines = "Demo Product A\nDemo Product B\nDemo Product C"

        raw = st.text_area(
            "Product lines (brand string, or `name | ingredient, ingredient`)",
            value=default_lines,
            height=120,
        )

        if st.button("Run medication pipeline", type="primary", key="e2e_med"):
            lines = [line for line in raw.splitlines() if line.strip()]

            result = run_medication_review_pipeline(
                lines,
                tenant_id=tenant_id,
                encounter_ref=encounter_ref,
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

                for citation in result["citations"]:
                    with st.container(border=True):
                        st.markdown(
                            f"**{citation.get('title')}** — "
                            f"{citation.get('issuer')} · "
                            f"ed. {citation.get('edition')} · "
                            f"effective {citation.get('effective_from')}"
                        )
                        st.caption(
                            f"{citation.get('filename')} lines "
                            f"{citation.get('line_start')}–"
                            f"{citation.get('line_end')} · "
                            f"section “{citation.get('heading')}”"
                        )
                        st.write(citation.get("excerpt"))

        else:
            st.markdown("#### Drug resolution")

            for resolution in result.get("resolutions", []):
                with st.container(border=True):
                    st.markdown(
                        f"**{resolution.get('query')}** → "
                        f"`{resolution.get('state')}`"
                    )
                    st.write(resolution.get("message"))

                    if resolution.get("candidates"):
                        st.json(resolution["candidates"])

                    if resolution.get("ingredients"):
                        st.json(resolution["ingredients"])

            st.markdown("#### Safety checks (deterministic)")

            for check in result.get("checks", []):
                status = check["status"]

                if status in (
                    "HIT",
                    "UNVERIFIED_INPUT",
                    "PARTIAL_COVERAGE",
                    "SERVICE_UNAVAILABLE",
                    "SOURCE_CONFLICT",
                    "DATA_EXPIRED",
                ):
                    icon = "🔴"
                elif status == "NOT_CHECKED":
                    icon = "🟡"
                else:
                    icon = "🟢"

                with st.container(border=True):
                    st.markdown(f"{icon} **{check['check']}** — `{status}`")
                    st.write(check["message"])

                    if check.get("details"):
                        st.json(check["details"])

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
                    "note": (
                        "Session checkbox only; not a production approval record"
                    ),
                },
                event_status="CONFIRMED",
            )
            st.success("Confirmation recorded in audit.")


with tab_meds:
    st.subheader("Medication-review path")
    st.markdown(
        "Enter synthetic product strings. Ambiguous brands "
        "(e.g. **Demo Product C**) remain unresolved. Duplicate ingredient "
        "tokens produce a `HIT` on the demo rule only."
    )

    st.markdown("**Catalogue brands (synthetic):**")
    st.code(
        "\n".join(
            f"{drug['brand']} → "
            f"{[ingredient['name'] for ingredient in drug['ingredients']]}"
            for drug in DRUG_CATALOGUE.values()
        ),
        language=None,
    )

    example = "Demo Product A\nDemo Product B\nDemo Product C"

    raw = st.text_area(
        "Product lines",
        value=example,
        height=120,
        key="med_tab_raw",
    )

    if st.button("Resolve & check", key="med_tab_btn"):
        lines = [line for line in raw.splitlines() if line.strip()]

        output = run_medication_review_pipeline(
            lines,
            tenant_id=tenant_id,
            encounter_ref=encounter_ref,
        )

        for resolution in output["resolutions"]:
            st.write(
                f"**{resolution['query']}** → `{resolution['state']}` — "
                f"{resolution['message']}"
            )

        for check in output["checks"]:
            st.write(
                f"`{check['status']}` · {check['check']}: {check['message']}"
            )


with tab_ref:
    st.subheader("Clinical reference path")
    st.markdown(
        "Ask about the **assessment section**, **versioning**, or "
        "**eligibility** in the fictional demo corpus. Pediatric filter will "
        "abstain on adult-only sources."
    )

    q2 = st.text_input(
        "Reference question",
        value="assessment section required elements",
        key="ref_q",
    )

    if st.button("Retrieve & gate", key="ref_btn"):
        pop = None if population == "unspecified" else population

        output = run_reference_pipeline(
            q2,
            population=pop,
            tenant_id=tenant_id,
        )

        st.markdown(output["answer"])
        st.json(
            {
                "gate": output["gate"],
                "evidence_count": output["evidence_count"],
                "abstained": output["abstained"],
            }
        )


with tab_states:
    st.subheader("Eight-state safety contract")
    st.write(
        "Every medication check returns **exactly one** of these states. "
        "Missing coverage is never rendered as safe."
    )

    cols = st.columns(4)

    for index, state in enumerate(VALID_STATES):
        cols[index % 4].code(state, language=None)

    st.subheader("Rule coverage manifest (honest disclosure)")
    st.json(COVERAGE_MANIFEST)

    st.caption(
        f"Rule version `{RULE_VERSION}`. Unsupported checks return "
        "`NOT_CHECKED` or contribute to `PARTIAL_COVERAGE` — never a silent "
        "all-clear."
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
        "Maps to Supabase `source_versions`. Demo corpus rows can be "
        "registered below."
    )

    col_a, col_b = st.columns(2)

    with col_a:
        source_name = st.text_input(
            "source_name",
            value="demo_assessment_workflow.md",
        )
        version_label = st.text_input("version_label", value="1")

    with col_b:
        source_status = st.selectbox(
            "status",
            ["DRAFT", "verified-live", "withdrawn"],
        )
        content_hash = st.text_input(
            "content_hash (optional)",
            value="",
        )

    if st.button("Register source version"):
        if not supabase_configured():
            st.error(
                "Supabase not configured — cannot write source_versions."
            )
        else:
            registered = register_source_version(
                source_name,
                version_label,
                content_hash=content_hash or None,
                status=source_status,
            )

            if registered:
                st.success("Registered.")

                write_audit_event(
                    "source_version_registered",
                    {
                        "source_name": source_name,
                        "version_label": version_label,
                        "status": source_status,
                    },
                    event_status="OK",
                )
            else:
                st.error(
                    "Registration failed (check service role key and RLS)."
                )

    versions = list_source_versions(limit=20)

    if versions:
        st.dataframe(versions, width="stretch", hide_index=True)
    elif supabase_configured():
        st.caption("No source_versions rows yet.")


st.divider()
st.caption(
    "BRAHMO Clinical AI prototype · Not for clinical use · No real patient data"
)
