
"""
BRAHMO Clinical AI — Streamlit Community Cloud MVP

Status: engineering prototype only.
Not for clinical use. Not a medical device. Not approved for real patients.
Do not enter real patient data.
"""

from __future__ import annotations

import streamlit as st

from brahmo import __version__
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


# ---------------------------------------------------------
# Page configuration
# ---------------------------------------------------------

st.set_page_config(
    page_title="BRAHMO Clinical AI (Demo)",
    page_icon="🩺",
    layout="wide",
)

st.title("BRAHMO Clinical AI — Doctor-facing demo")
st.caption(
    f"Prototype v{__version__} · Streamlit Community Cloud · "
    "Not for clinical use"
)

st.error(
    "**Safety notice:** This application is an engineering prototype. "
    "It is **not clinically validated**, is **not a medical device**, and "
    "is **not approved for use with real patients**. Do not enter identifiable "
    "patient data. Outputs must not guide diagnosis, prescribing, or care decisions."
)


# ---------------------------------------------------------
# Architecture overview
# ---------------------------------------------------------

with st.expander("Architecture alignment (read once)", expanded=False):
    st.markdown(
        """
| Stage | Demo behaviour |
|---|---|
| Identity / tenant | Synthetic tenant label only; no real authentication |
| Intent router | Keyword classifier routes to medication review or clinical reference |
| Drug identity graph | Small synthetic catalogue; ambiguity remains unresolved |
| Deterministic safety rail | Eight-state contract; demo rules only |
| Hybrid retrieval | Local lexical search over fictional `knowledge/` files |
| Evidence sufficiency gate | Blocks composition when applicable verified-live evidence is absent |
| Grounded composition | Deterministic excerpts and citations; no LLM required |
| Doctor approval boundary | Draft versus confirmation; no autonomous export |
| Audit | Supabase when configured; otherwise local/in-memory fallback |

**Not implemented:** real drug master, production interaction/allergy rules,
Indian regulatory event feed, production RAG/LLM, authentication, tenant isolation,
encryption, clinical approvals, or regulatory clearance.
"""
    )


# ---------------------------------------------------------
# Sidebar: demo scope and configuration status
# ---------------------------------------------------------

with st.sidebar:
    st.header("Session scope (demo)")

    tenant_id = st.text_input(
        "Tenant ID",
        value="demo-tenant-001",
    )

    encounter_ref = st.text_input(
        "Encounter ref (pseudonymous)",
        value="enc-demo-001",
    )

    population = st.selectbox(
        "Population filter (reference path)",
        ["adult", "pediatric", "unspecified"],
    )

    st.divider()

    st.markdown("**Versions**")
    st.code(
        f"Drug map: {MAPPING_VERSION}\nRules: {RULE_VERSION}",
        language=None,
    )

    st.divider()

    st.markdown("**Persistence**")

    if supabase_configured():
        st.success("Supabase configured")
        st.caption("Audit persistence depends on the configured database and permissions.")
    else:
        st.warning(
            "Supabase is not configured. Audit events may use a local or in-memory "
            "fallback and may be lost when Community Cloud restarts."
        )

    st.caption("Never store protected health information in audit payloads.")


# ---------------------------------------------------------
# Main tabs
# ---------------------------------------------------------

(
    tab_pipeline,
    tab_meds,
    tab_ref,
    tab_states,
    tab_audit,
) = st.tabs(
    [
        "1 · End-to-end pipeline",
        "2 · Medication review",
        "3 · Clinical reference",
        "4 · Eight states & coverage",
        "5 · Audit & sources",
    ]
)


# ---------------------------------------------------------
# Tab 1: End-to-end pipeline
# ---------------------------------------------------------

with tab_pipeline:
    st.subheader("End-to-end workflow (demo)")

    st.markdown(
        """
1. Establish the demo scope in the sidebar.
2. Enter a fictional clinical-reference question or synthetic product lines.
3. The router selects a processing path.
4. The pipeline performs demo drug resolution and checks, or evidence retrieval.
5. Review the result. The confirmation checkbox is only a demo interaction.
"""
    )

    mode = st.radio(
        "Input mode",
        [
            "Clinical reference question",
            "Medication review (product lines)",
        ],
        horizontal=True,
        key="pipeline_mode",
    )

    if mode.startswith("Clinical"):
        question = st.text_input(
            "Question",
            value=(
                "What does the current demo workflow say "
                "about the assessment section?"
            ),
            key="e2e_reference_question",
        )

        if st.button(
            "Run reference pipeline",
            type="primary",
            key="e2e_ref",
        ):
            population_filter = (
                None if population == "unspecified" else population
            )

            try:
                result = run_reference_pipeline(
                    question,
                    population=population_filter,
                    tenant_id=tenant_id,
                )
                st.session_state["last_result"] = result
                st.session_state.pop("confirmation_logged", None)
            except Exception as exc:
                st.error(
                    "The reference pipeline failed. Check the Streamlit logs "
                    "for diagnostic details."
                )
                st.exception(exc)

    else:
        default_lines = (
            "Demo Product A\n"
            "Demo Product B\n"
            "Demo Product C"
        )

        raw_lines = st.text_area(
            "Product lines (brand, or name | ingredient, ingredient)",
            value=default_lines,
            height=120,
            key="e2e_medication_lines",
        )

        if st.button(
            "Run medication pipeline",
            type="primary",
            key="e2e_med",
        ):
            lines = [
                line.strip()
                for line in raw_lines.splitlines()
                if line.strip()
            ]

            if not lines:
                st.warning("Enter at least one synthetic product line.")
            else:
                try:
                    result = run_medication_review_pipeline(
                        lines,
                        tenant_id=tenant_id,
                        encounter_ref=encounter_ref,
                    )
                    st.session_state["last_result"] = result
                    st.session_state.pop("confirmation_logged", None)
                except Exception as exc:
                    st.error(
                        "The medication pipeline failed. Check the Streamlit "
                        "logs for diagnostic details."
                    )
                    st.exception(exc)

    result = st.session_state.get("last_result")

    if result:
        st.divider()

        st.markdown(f"**Pipeline:** `{result.get('pipeline', 'unknown')}`")

        # Clinical reference result
        if result.get("pipeline") == "clinical_reference":
            gate = result.get("gate", {})

            if result.get("abstained"):
                st.warning(result.get("answer", "The pipeline abstained."))
            else:
                st.success("Grounded demo answer — excerpts only")
                st.markdown(result.get("answer", ""))

            st.markdown("#### Evidence sufficiency gate")
            st.json(gate)

            citations = result.get("citations", [])

            if citations:
                st.markdown("#### Citations")

                for citation in citations:
                    with st.container(border=True):
                        st.markdown(
                            f"**{citation.get('title', 'Untitled source')}** — "
                            f"{citation.get('issuer', 'Unknown issuer')} · "
                            f"Edition: {citation.get('edition', 'N/A')} · "
                            f"Effective: {citation.get('effective_from', 'N/A')}"
                        )

                        st.caption(
                            f"{citation.get('filename', 'Unknown file')} · "
                            f"Lines {citation.get('line_start', '?')}–"
                            f"{citation.get('line_end', '?')} · "
                            f"Section: {citation.get('heading', 'N/A')}"
                        )

                        st.write(citation.get("excerpt", ""))

        # Medication result
        else:
            st.markdown("#### Drug resolution")

            for resolution in result.get("resolutions", []):
                with st.container(border=True):
                    st.markdown(
                        f"**{resolution.get('query', 'Unknown query')}** → "
                        f"`{resolution.get('state', 'UNKNOWN')}`"
                    )

                    st.write(resolution.get("message", ""))

                    if resolution.get("candidates"):
                        st.markdown("**Candidates**")
                        st.json(resolution["candidates"])

                    if resolution.get("ingredients"):
                        st.markdown("**Ingredients**")
                        st.json(resolution["ingredients"])

            st.markdown("#### Deterministic demo checks")

            for check in result.get("checks", []):
                status = check.get("status", "UNKNOWN")

                if status in {
                    "HIT",
                    "UNVERIFIED_INPUT",
                    "PARTIAL_COVERAGE",
                    "SERVICE_UNAVAILABLE",
                    "SOURCE_CONFLICT",
                    "DATA_EXPIRED",
                }:
                    status_icon = "🔴"
                elif status == "NOT_CHECKED":
                    status_icon = "🟡"
                else:
                    status_icon = "⚪"

                with st.container(border=True):
                    st.markdown(
                        f"{status_icon} **{check.get('check', 'Unnamed check')}** "
                        f"— `{status}`"
                    )

                    st.write(check.get("message", ""))

                    if check.get("details"):
                        st.json(check["details"])

            st.info(
                result.get(
                    "notice",
                    "Engineering prototype output; not for clinical use.",
                )
            )

        st.divider()

        st.caption(
            "The following checkbox is a demo-only interaction. "
            "It is not a clinical approval or legal signature."
        )

        confirmed = st.checkbox(
            "Mark this draft as demo-confirmed (session only)",
            key="confirm_box",
        )

        if confirmed and not st.session_state.get("confirmation_logged", False):
            try:
                write_audit_event(
                    "doctor_confirmation_demo",
                    {
                        "tenant_id": tenant_id,
                        "encounter_ref": encounter_ref,
                        "pipeline": result.get("pipeline"),
                        "note": (
                            "Session checkbox only; not a production "
                            "approval record."
                        ),
                    },
                    event_status="CONFIRMED",
                )

                st.session_state["confirmation_logged"] = True
                st.success("Demo confirmation event submitted to the audit layer.")

            except Exception:
                st.error(
                    "The demo confirmation could not be written to the audit layer."
                )

        elif not confirmed:
            st.session_state["confirmation_logged"] = False


# ---------------------------------------------------------
# Tab 2: Medication review
# ---------------------------------------------------------

with tab_meds:
    st.subheader("Medication-review path")

    st.warning(
        "Use fictional product strings only. The catalogue and checks are "
        "demonstration logic, not a real medication-safety database."
    )

    st.markdown(
        "Ambiguous synthetic brands, such as **Demo Product C**, should remain "
        "unresolved. Duplicate ingredient tokens may trigger a demo `HIT`."
    )

    st.markdown("**Synthetic catalogue**")

    try:
        catalogue_lines = [
            f"{item['brand']} → "
            f"{[ingredient['name'] for ingredient in item['ingredients']]}"
            for item in DRUG_CATALOGUE.values()
        ]

        st.code("\n".join(catalogue_lines), language=None)

    except (KeyError, TypeError):
        st.info("The synthetic catalogue could not be displayed.")

    medication_text = st.text_area(
        "Product lines",
        value="Demo Product A\nDemo Product B\nDemo Product C",
        height=120,
        key="med_tab_raw",
    )

    if st.button("Resolve & check", key="med_tab_btn"):
        lines = [
            line.strip()
            for line in medication_text.splitlines()
            if line.strip()
        ]

        if not lines:
            st.warning("Enter at least one synthetic product line.")
        else:
            try:
                output = run_medication_review_pipeline(
                    lines,
                    tenant_id=tenant_id,
                    encounter_ref=encounter_ref,
                )

                st.markdown("#### Resolution results")

                for resolution in output.get("resolutions", []):
                    st.write(
                        f"**{resolution.get('query')}** → "
                        f"`{resolution.get('state')}` — "
                        f"{resolution.get('message', '')}"
                    )

                st.markdown("#### Check results")

                for check in output.get("checks", []):
                    st.write(
                        f"`{check.get('status')}` · "
                        f"{check.get('check')}: {check.get('message', '')}"
                    )

            except Exception as exc:
                st.error("Medication review failed. Check the application logs.")
                st.exception(exc)


# ---------------------------------------------------------
# Tab 3: Clinical reference
# ---------------------------------------------------------

with tab_ref:
    st.subheader("Clinical-reference path")

    st.warning(
        "This tab searches a fictional demonstration corpus. It is not a "
        "clinical reference service and must not be used for care decisions."
    )

    st.markdown(
        "Example topics: the assessment section, source versioning, or eligibility. "
        "The pediatric filter may abstain when the fictional source is adult-only."
    )

    reference_question = st.text_input(
        "Reference question",
        value="assessment section required elements",
        key="ref_q",
    )

    if st.button("Retrieve & gate", key="ref_btn"):
        population_filter = (
            None if population == "unspecified" else population
        )

        try:
            output = run_reference_pipeline(
                reference_question,
                population=population_filter,
                tenant_id=tenant_id,
            )

            if output.get("abstained"):
                st.warning(output.get("answer", "The pipeline abstained."))
            else:
                st.markdown(output.get("answer", ""))

            st.markdown("#### Gate result")

            st.json(
                {
                    "gate": output.get("gate", {}),
                    "evidence_count": output.get("evidence_count", 0),
                    "abstained": output.get("abstained", True),
                }
            )

            citations = output.get("citations", [])

            if citations:
                st.markdown("#### Citations")

                for citation in citations:
                    with st.container(border=True):
                        st.markdown(
                            f"**{citation.get('title', 'Untitled source')}**"
                        )
                        st.caption(
                            f"{citation.get('filename', 'Unknown file')} · "
                            f"Lines {citation.get('line_start', '?')}–"
                            f"{citation.get('line_end', '?')}"
                        )
                        st.write(citation.get("excerpt", ""))

        except Exception as exc:
            st.error("Reference retrieval failed. Check the application logs.")
            st.exception(exc)


# ---------------------------------------------------------
# Tab 4: Safety states and coverage
# ---------------------------------------------------------

with tab_states:
    st.subheader("Eight-state safety contract")

    st.write(
        "Every medication check should return exactly one configured state. "
        "Missing or unsupported coverage must never be interpreted as safe."
    )

    columns = st.columns(4)

    for index, state in enumerate(VALID_STATES):
        columns[index % 4].code(state, language=None)

    st.subheader("Rule coverage manifest")

    st.json(COVERAGE_MANIFEST)

    st.caption(
        f"Rule version: `{RULE_VERSION}`. Unsupported checks should return "
        "`NOT_CHECKED` or contribute to `PARTIAL_COVERAGE`, never a silent all-clear."
    )


# ---------------------------------------------------------
# Tab 5: Audit and source registry
# ---------------------------------------------------------

with tab_audit:
    st.subheader("Audit events")

    if supabase_configured():
        st.success("Supabase is configured for the audit layer.")
    else:
        st.warning(
            "Supabase is not configured. Local or in-memory audit events may "
            "be lost when Streamlit Community Cloud restarts."
        )

    if st.button("Refresh audit events", key="refresh_audit"):
        st.session_state["refresh_audit_requested"] = True

    try:
        events = recent_audit_events(limit=30)

        if events:
            st.dataframe(
                events,
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No audit events yet. Run a demo pipeline first.")

    except Exception:
        st.error("Could not retrieve audit events. Check Supabase configuration and logs.")

    st.divider()

    st.subheader("Source versions registry")

    st.caption(
        "This section uses the configured `source_versions` table. "
        "Register fictional demonstration sources only."
    )

    col_a, col_b = st.columns(2)

    with col_a:
        source_name = st.text_input(
            "source_name",
            value="demo_assessment_workflow.md",
        )

        version_label = st.text_input(
            "version_label",
            value="1",
        )

    with col_b:
        source_status = st.selectbox(
            "status",
            ["DRAFT", "verified-live", "withdrawn"],
        )

        content_hash = st.text_input(
            "content_hash (optional)",
            value="",
        )

    if st.button("Register source version", key="register_source"):
        if not supabase_configured():
            st.error("Supabase is not configured; cannot register the source.")
        elif not source_name.strip() or not version_label.strip():
            st.warning("Source name and version label are required.")
        else:
            try:
                success = register_source_version(
                    source_name.strip(),
                    version_label.strip(),
                    content_hash=content_hash.strip() or None,
                    status=source_status,
                )

                if success:
                    try:
                        write_audit_event(
                            "source_version_registered",
                            {
                                "source_name": source_name.strip(),
                                "version_label": version_label.strip(),
                                "status": source_status,
                            },
                            event_status="OK",
                        )
                    except Exception:
                        st.warning(
                            "The source was registered, but the audit event "
                            "could not be recorded."
                        )

                    st.success("Source registration completed.")
                else:
                    st.error(
                        "Source registration failed. Check the source_versions "
                        "schema, database permissions, and application logs."
                    )

            except Exception:
                st.error("Source registration failed. Check the application logs.")

    try:
        versions = list_source_versions(limit=20)

        if versions:
            st.dataframe(
                versions,
                width="stretch",
                hide_index=True,
            )
        elif supabase_configured():
            st.caption("No source versions were returned.")

    except Exception:
        st.error(
            "Could not retrieve source versions. Verify that the table exists "
            "and the audit module handles database errors."
        )


# ---------------------------------------------------------
# Footer
# ---------------------------------------------------------

st.divider()

st.caption(
    "BRAHMO Clinical AI prototype · Engineering demonstration only · "
    "Not for clinical use · Do not enter real patient data"
)
