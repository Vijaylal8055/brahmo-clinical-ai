
from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from brahmo.__version__ import APP_VERSION
from brahmo import safety, drug_graph, orchestrator, audit


# -------------------------------------------------------------------
# Page configuration
# -------------------------------------------------------------------

st.set_page_config(
    page_title="BRAHMO Clinical AI",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = "BRAHMO Clinical AI"


# -------------------------------------------------------------------
# Styling
# -------------------------------------------------------------------

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b1017;
        color: #edf2f7;
    }
    [data-testid="stSidebar"] {
        background-color: #111925;
    }
    .brahmo-header {
        padding: 1.2rem 1.5rem;
        border: 1px solid #34445a;
        border-radius: 14px;
        background: linear-gradient(120deg, #111925, #192638);
        margin-bottom: 1rem;
    }
    .brahmo-title {
        color: #e8c875;
        font-size: 2.1rem;
        font-weight: 750;
        margin: 0;
    }
    .brahmo-subtitle {
        color: #b7c4d4;
        margin-top: .4rem;
    }
    .prototype-warning {
        padding: .8rem 1rem;
        border: 1px solid #9c7336;
        border-radius: 9px;
        background: #2a2115;
        color: #ffdfa0;
        margin: .8rem 0 1rem 0;
    }
    div[data-testid="stMetric"] {
        background: #121c29;
        border: 1px solid #2c3c50;
        border-radius: 10px;
        padding: .8rem;
    }
    div.stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }
    h1, h2, h3 {
        color: #e8c875;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def json_safe(value: Any) -> Any:
    """Convert common Python objects to JSON-friendly values."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [json_safe(v) for v in value]
        return str(value)


def show_result(result: Any) -> None:
    """Render pipeline results without assuming one fixed result shape."""
    if result is None:
        st.info("The workflow returned no result.")
        return

    if isinstance(result, str):
        st.markdown(result)
        return

    if isinstance(result, dict):
        # Render common summary fields first when available.
        preferred = (
            "status",
            "state",
            "decision",
            "summary",
            "answer",
            "response",
            "message",
            "warnings",
            "alerts",
            "citations",
            "evidence",
        )

        rendered = set()

        for key in preferred:
            if key in result:
                st.markdown(f"**{key.replace('_', ' ').title()}**")
                value = result[key]
                if isinstance(value, (dict, list, tuple)):
                    st.json(json_safe(value))
                else:
                    st.write(value)
                rendered.add(key)

        remaining = {k: v for k, v in result.items() if k not in rendered}
        if remaining:
            with st.expander("Full structured result"):
                st.json(json_safe(remaining))
        return

    if isinstance(result, (list, tuple)):
        for index, item in enumerate(result, start=1):
            with st.expander(f"Result {index}", expanded=index == 1):
                show_result(item)
        return

    st.write(result)


def invoke_pipeline(function: Any, user_input: str, **context: Any) -> Any:
    """
    Call a pipeline using its declared parameter names.

    This helper accommodates common input names. If a pipeline requires
    a project-specific argument not covered here, its signature must be
    mapped explicitly to that argument.
    """
    signature = inspect.signature(function)
    parameters = signature.parameters

    aliases = {
        "query": user_input,
        "question": user_input,
        "text": user_input,
        "input": user_input,
        "user_input": user_input,
        "clinical_question": user_input,
        "reference_question": user_input,
        "query_text": user_input,
        "drug": context.get("drug_name", user_input),
        "drug_name": context.get("drug_name", user_input),
        "medication": context.get("drug_name", user_input),
        "medicine": context.get("drug_name", user_input),
        "medication_name": context.get("drug_name", user_input),
        "patient_context": context.get("patient_context", {}),
        "patient_data": context.get("patient_context", {}),
        "context": context.get("patient_context", {}),
        "age": context.get("age"),
        "allergies": context.get("allergies", []),
        "conditions": context.get("conditions", []),
        "current_medications": context.get("current_medications", []),
    }

    kwargs = {}
    positional = []

    for name, parameter in parameters.items():
        if name in ("self", "cls"):
            continue

        if name in context:
            kwargs[name] = context[name]
        elif name in aliases and aliases[name] is not None:
            kwargs[name] = aliases[name]
        elif parameter.default is inspect.Parameter.empty and parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            # Use the entered text for the first unrecognised required input.
            if not positional and not kwargs:
                positional.append(user_input)
            else:
                raise TypeError(
                    f"Pipeline requires unmapped parameter '{name}'. "
                    "Update invoke_pipeline() with the correct mapping."
                )

    return function(*positional, **kwargs)


def record_audit(event_type: str, status: str, details: dict | None = None) -> None:
    """Record an audit event without interrupting the UI."""
    try:
        audit.write_audit_event(
            event_type=event_type,
            event_status=status,
            details=details or {},
        )
    except Exception as exc:
        st.warning(
            "The action completed in the UI, but the audit call raised an "
            f"error: {type(exc).__name__}: {exc}"
        )


def get_attr(module: Any, name: str, default: Any = None) -> Any:
    """Safely read an optional module constant."""
    return getattr(module, name, default)


def get_source_error() -> str | None:
    """Read detailed audit/Supabase diagnostics when the module supports it."""
    error_fn = getattr(audit, "supabase_last_error", None)
    if callable(error_fn):
        try:
            return error_fn()
        except Exception:
            return None
    return None


def safe_call(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call an optional helper while allowing the UI to show its failure."""
    return function(*args, **kwargs)


# -------------------------------------------------------------------
# Sidebar
# -------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🩺 BRAHMO")
    st.caption("Clinical AI engineering prototype")
    st.divider()

    st.markdown(f"**Application version:** {APP_VERSION}")
    st.markdown(
        f"**Runtime:** {'Streamlit Cloud' if os.getenv('STREAMLIT_SHARING_MODE') else 'Streamlit'}"
    )

    st.divider()
    st.markdown("### Safety boundary")
    st.caption(
        "Demonstration only. Do not enter patient-identifiable information. "
        "Outputs are not medical advice and must not be used to make clinical "
        "decisions."
    )


# -------------------------------------------------------------------
# Header
# -------------------------------------------------------------------

st.markdown(
    f"""
    <div class="brahmo-header">
        <p class="brahmo-title">BRAHMO Clinical AI</p>
        <p class="brahmo-subtitle">
            Evidence-aware clinical workflow · Medication safety demonstrations
            · Source governance · Audit visibility
        </p>
    </div>
    <div class="prototype-warning">
        <strong>Prototype only:</strong>
        Use synthetic examples only. This application is not approved for
        diagnosis, prescribing, medication changes, or patient care.
    </div>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------
# Resolve project components
# -------------------------------------------------------------------

medication_pipeline = getattr(
    orchestrator, "run_medication_review_pipeline", None
)
reference_pipeline = getattr(
    orchestrator, "run_reference_pipeline", None
)

valid_states = get_attr(safety, "VALID_STATES", [])
coverage_manifest = get_attr(safety, "COVERAGE_MANIFEST", {})
rule_version = get_attr(safety, "RULE_VERSION", "unknown")
mapping_version = get_attr(safety, "MAPPING_VERSION", "unknown")
drug_catalogue = get_attr(drug_graph, "DRUG_CATALOGUE", {})


# -------------------------------------------------------------------
# Top-level tabs
# -------------------------------------------------------------------

tab_pipeline, tab_medication, tab_reference, tab_coverage, tab_audit = st.tabs(
    [
        "End-to-end pipeline",
        "Medication review",
        "Clinical reference",
        "States & coverage",
        "Audit & sources",
    ]
)


# ===================================================================
# TAB 1: END-TO-END PIPELINE
# ===================================================================

with tab_pipeline:
    st.subheader("End-to-end workflow")
    st.write(
        "Submit a synthetic clinical question to the reference workflow. "
        "Inspect the result and its evidence before considering any next step."
    )

    with st.form("reference_pipeline_form"):
        reference_question = st.text_area(
            "Clinical reference question",
            placeholder=(
                "Example: Demonstrate how the system retrieves and presents "
                "evidence for a fictional reference question."
            ),
            height=120,
        )
        run_reference = st.form_submit_button(
            "Run reference workflow",
            type="primary",
            width="stretch",
        )

    if run_reference:
        if not reference_question.strip():
            st.warning("Enter a question first.")
        elif not callable(reference_pipeline):
            st.error(
                "The function run_reference_pipeline was not found in "
                "brahmo.orchestrator."
            )
        else:
            with st.spinner("Running reference workflow..."):
                try:
                    result = invoke_pipeline(
                        reference_pipeline,
                        reference_question.strip(),
                    )
                    st.session_state["last_reference_result"] = json_safe(result)
                    record_audit(
                        "reference_pipeline_demo",
                        "COMPLETED",
                        {"input_type": "synthetic_demo"},
                    )
                    st.success("Workflow finished. Review the result below.")
                except Exception as exc:
                    record_audit(
                        "reference_pipeline_demo",
                        "FAILED",
                        {"error_type": type(exc).__name__},
                    )
                    st.error(f"Reference workflow failed: {exc}")

    if "last_reference_result" in st.session_state:
        st.markdown("### Workflow result")
        show_result(st.session_state["last_reference_result"])


# ===================================================================
# TAB 2: MEDICATION REVIEW
# ===================================================================

with tab_medication:
    st.subheader("Medication review demonstration")
    st.caption(
        "Synthetic data only. This screen does not determine whether a "
        "medicine is safe for a real person."
    )

    with st.form("medication_review_form"):
        drug_name = st.text_input(
            "Medicine or ingredient",
            placeholder="Enter a fictional or non-patient-specific example",
        )

        patient_age = st.number_input(
            "Demo age (optional)",
            min_value=0,
            max_value=120,
            value=0,
            help="Leave as 0 if not applicable. Do not enter real patient data.",
        )

        allergies_text = st.text_input(
            "Demo allergies (comma-separated)",
            placeholder="Example: synthetic-allergy-A",
        )

        conditions_text = st.text_input(
            "Demo conditions (comma-separated)",
            placeholder="Example: synthetic-condition-A",
        )

        current_meds_text = st.text_input(
            "Demo current medicines (comma-separated)",
            placeholder="Example: synthetic-medicine-A",
        )

        run_medication = st.form_submit_button(
            "Run medication review demo",
            type="primary",
            width="stretch",
        )

    if run_medication:
        if not drug_name.strip():
            st.warning("Enter a medicine or ingredient to continue.")
        elif not callable(medication_pipeline):
            st.error(
                "The function run_medication_review_pipeline was not found "
                "in brahmo.orchestrator."
            )
        else:
            patient_context = {
                "age": int(patient_age) if patient_age else None,
                "allergies": [
                    x.strip()
                    for x in allergies_text.split(",")
                    if x.strip()
                ],
                "conditions": [
                    x.strip()
                    for x in conditions_text.split(",")
                    if x.strip()
                ],
                "current_medications": [
                    x.strip()
                    for x in current_meds_text.split(",")
                    if x.strip()
                ],
                "synthetic_demo": True,
            }

            with st.spinner("Running medication review demo..."):
                try:
                    result = invoke_pipeline(
                        medication_pipeline,
                        drug_name.strip(),
                        drug_name=drug_name.strip(),
                        patient_context=patient_context,
                        age=patient_context["age"],
                        allergies=patient_context["allergies"],
                        conditions=patient_context["conditions"],
                        current_medications=patient_context["current_medications"],
                    )

                    st.session_state["last_medication_result"] = json_safe(result)

                    record_audit(
                        "medication_review_demo",
                        "COMPLETED",
                        {
                            "synthetic_demo": True,
                            "drug_input_provided": True,
                        },
                    )

                    st.success(
                        "The demo workflow returned a result. It is not a "
                        "clinical recommendation."
                    )
                except Exception as exc:
                    record_audit(
                        "medication_review_demo",
                        "FAILED",
                        {
                            "synthetic_demo": True,
                            "error_type": type(exc).__name__,
                        },
                    )
                    st.error(f"Medication review failed: {exc}")

    if "last_medication_result" in st.session_state:
        st.markdown("### Medication review result")
        show_result(st.session_state["last_medication_result"])


# ===================================================================
# TAB 3: CLINICAL REFERENCE
# ===================================================================

with tab_reference:
    st.subheader("Clinical reference")
    st.write(
        "Use this area to inspect the reference workflow and the project's "
        "available drug-catalogue metadata. Catalogue entries are not proof "
        "of clinical completeness or correctness."
    )

    ref_col1, ref_col2 = st.columns(2)

    with ref_col1:
        st.metric(
            "Reference pipeline",
            "Available" if callable(reference_pipeline) else "Not found",
        )

    with ref_col2:
        st.metric(
            "Drug catalogue",
            "Available" if drug_catalogue else "Empty / not found",
        )

    if drug_catalogue:
        with st.expander("Inspect drug catalogue"):
            if isinstance(drug_catalogue, dict):
                st.json(json_safe(drug_catalogue))
            elif isinstance(drug_catalogue, (list, tuple)):
                st.json(json_safe(list(drug_catalogue)))
            else:
                st.write(drug_catalogue)
    else:
        st.info(
            "No DRUG_CATALOGUE constant was exposed by brahmo.drug_graph. "
            "This does not necessarily mean the drug graph itself is unavailable."
        )

    st.markdown("### Reference workflow")
    reference_question_2 = st.text_area(
        "Question to send to the reference pipeline",
        key="clinical_reference_question",
        placeholder="Enter a synthetic reference question",
        height=100,
    )

    if st.button(
        "Retrieve reference result",
        key="clinical_reference_run",
        type="primary",
        width="stretch",
    ):
        if not reference_question_2.strip():
            st.warning("Enter a question first.")
        elif not callable(reference_pipeline):
            st.error("Reference pipeline function is unavailable.")
        else:
            try:
                with st.spinner("Retrieving reference result..."):
                    result = invoke_pipeline(
                        reference_pipeline,
                        reference_question_2.strip(),
                    )
                st.session_state["clinical_reference_result"] = json_safe(result)
                record_audit(
                    "clinical_reference_demo",
                    "COMPLETED",
                    {"synthetic_demo": True},
                )
                show_result(result)
            except Exception as exc:
                record_audit(
                    "clinical_reference_demo",
                    "FAILED",
                    {"error_type": type(exc).__name__},
                )
                st.error(f"Reference retrieval failed: {exc}")

    if "clinical_reference_result" in st.session_state:
        with st.expander("Last reference result"):
            st.json(st.session_state["clinical_reference_result"])


# ===================================================================
# TAB 4: EIGHT STATES & COVERAGE
# ===================================================================

with tab_coverage:
    st.subheader("Workflow states and coverage")
    st.write(
        "These values are read from the project's safety module when "
        "available. They are configuration metadata, not evidence of "
        "clinical validation."
    )

    version_col1, version_col2 = st.columns(2)

    with version_col1:
        st.metric("Safety rule version", str(rule_version))

    with version_col2:
        st.metric("Mapping version", str(mapping_version))

    st.markdown("### Valid states")

    if valid_states:
        if isinstance(valid_states, dict):
            states_to_show = list(valid_states.items())
            for state_name, description in states_to_show:
                with st.expander(str(state_name)):
                    st.write(description)
        elif isinstance(valid_states, (list, tuple, set)):
            for state in valid_states:
                st.markdown(f"- `{state}`")
        else:
            st.write(valid_states)
    else:
        st.info(
            "VALID_STATES was not exposed as a public constant by "
            "brahmo.safety."
        )

    st.markdown("### Coverage manifest")

    if coverage_manifest:
        st.json(json_safe(coverage_manifest))
    else:
        st.info(
            "COVERAGE_MANIFEST was not exposed by brahmo.safety. "
            "If it lives in another module, update the import mapping in app.py."
        )

    st.markdown("### Release boundary")
    st.warning(
        "Do not interpret the presence of a state, rule, mapping, source, or "
        "catalogue entry as proof that a clinical use case has been validated. "
        "Release decisions require independent clinical, legal, security, "
        "and quality review."
    )


# ===================================================================
# TAB 5: AUDIT & SOURCES
# ===================================================================

with tab_audit:
    st.subheader("Audit events")
    st.write(
        "Events are intended to be persisted to Supabase. In-memory fallback "
        "events, if used by the audit module, are not durable across app restarts."
    )

    refresh_col, status_col = st.columns([1, 2])

    with refresh_col:
        refresh_audit = st.button(
            "Refresh audit log",
            width="stretch",
        )

    if refresh_audit:
        st.rerun()

    try:
        events = audit.recent_audit_events()
        if events:
            st.dataframe(
                events,
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No audit events were returned. Run a demo workflow, then refresh."
            )
    except Exception as exc:
        st.error(f"Unable to load audit events: {exc}")

    st.divider()
    st.subheader("Source version registry")

    with st.form("source_registration_form"):
        source_name = st.text_input(
            "Source name",
            placeholder="Example: demo-reference-source",
        )
        version_label = st.text_input(
            "Version label",
            placeholder="Example: v1.0-demo",
        )
        content_hash = st.text_input(
            "Content hash (optional)",
            placeholder="SHA-256 hash or internal version identifier",
        )
        source_status = st.selectbox(
            "Status",
            options=["DRAFT", "ACTIVE", "RETIRED", "REVOKED"],
            index=0,
        )

        register_source = st.form_submit_button(
            "Register source version",
            type="primary",
            width="stretch",
        )

    if register_source:
        if not source_name.strip() or not version_label.strip():
            st.warning("Source name and version label are required.")
        else:
            try:
                success = audit.register_source_version(
                    source_name=source_name.strip(),
                    version_label=version_label.strip(),
                    content_hash=content_hash.strip() or None,
                    status=source_status,
                )

                if success:
                    record_audit(
                        "source_version_registered",
                        "COMPLETED",
                        {
                            "source_name": source_name.strip(),
                            "version_label": version_label.strip(),
                            "status": source_status,
                        },
                    )
                    st.success("Source version registered.")
                    st.rerun()
                else:
                    st.error(
                        "Source registration failed. Check the source_versions "
                        "schema, Supabase credentials, database permissions, "
                        "and application logs."
                    )
                    error_detail = get_source_error()
                    if error_detail:
                        st.code(error_detail)

            except Exception as exc:
                st.error(f"Source registration failed: {exc}")
                error_detail = get_source_error()
                if error_detail:
                    st.code(error_detail)

    st.markdown("### Registered source versions")

    try:
        source_versions = audit.list_source_versions()
        if source_versions:
            st.dataframe(
                source_versions,
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No source versions returned by the registry.")
    except Exception as exc:
        st.error(f"Unable to list source versions: {exc}")

    st.divider()
    st.subheader("Supabase diagnostics")

    with st.expander("Inspect connection diagnostics"):
        configured_fn = getattr(audit, "supabase_configured", None)

        if callable(configured_fn):
            try:
                st.write(
                    "Supabase client initialized:",
                    bool(configured_fn()),
                )
            except Exception as exc:
                st.write("Supabase initialization check failed:", str(exc))
        else:
            st.info("supabase_configured() is not available in brahmo.audit.")

        diagnostic = get_source_error()
        st.write(
            "Latest diagnostic:",
            diagnostic if diagnostic else "No diagnostic recorded.",
        )

        st.caption(
            "Do not expose secret keys, access tokens, or other credentials in "
            "this panel or in public logs."
        )


# -------------------------------------------------------------------
# Footer
# -------------------------------------------------------------------

st.divider()

st.caption(
    f"{APP_NAME} · Version {APP_VERSION} · "
    f"Rendered at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
)

st.caption(
    "Engineering prototype only. Not for diagnosis, treatment, prescribing, "
    "or other clinical decision-making. No real patient data should be entered."
)
