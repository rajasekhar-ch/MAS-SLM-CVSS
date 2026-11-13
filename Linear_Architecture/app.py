"""Streamlit entry point for the Linear Architecture HR screening system."""

from pathlib import Path
import json

import streamlit as st

from mvp_pipeline import run_pipeline, save_artifacts


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "screening_outputs"
SIMULATION_API = "http://127.0.0.1:8000"

st.set_page_config(page_title="CV Screening System", page_icon="🛡️", layout="wide")
st.title("CV Screening System")
st.caption("A simple, transparent screening pipeline: parse → verify → score.")

with st.sidebar:
    st.header("Screening setup")
    job_id = st.text_input("Job ID", placeholder="e.g. SEC-001")
    st.caption("The job description and employee details are fetched using APIs.")
    job_api_url = st.text_input(
        "Job API URL",
        value=f"{SIMULATION_API}/jobs/{{job_id}}",
        help="Use the included simulation API endpoint or replace this with custom API.",
    )
    api_key = st.text_input(
        "API key",
        value="dev-api-key",
        type="password",
        help="Sent as X-API-Key to the job and employee API endpoints.",
    )
    credential_api_url = st.text_input(
        "Credential API URL",
        value=f"{SIMULATION_API}/certifications",
        help="Looks up each certification that states a certificate_id and checks its issuing organization and status. Certifications without an ID are not checked.",
    )
    institution_api_url = st.text_input(
        "Institution API URL",
        value=f"{SIMULATION_API}/institutions",
        help="Looks up each claimed educational institution by name (the institution only, not the course or graduation).",
    )
    notification_email = st.text_input("Notification email (optional)")
    show_saved_outputs = st.toggle("Show processed outputs", value=False)

uploads = st.file_uploader(
    "Upload one or more resume (PDFs or TXT)",
    type=["pdf","txt"],
    accept_multiple_files=True,
)

if show_saved_outputs:
    st.subheader("Previously processed outputs")
    saved_files = sorted(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []
    if not saved_files:
        st.info("No processed JSON outputs have been saved yet.")
    else:
        selected_file = st.selectbox(
            "Select a stage output",
            saved_files,
            format_func=lambda path: path.name,
        )
        st.download_button(
            "Download selected JSON",
            selected_file.read_bytes(),
            file_name=selected_file.name,
            mime="application/json",
        )
        st.json(json.loads(selected_file.read_text(encoding="utf-8")))

if st.button("Run screening", type="primary", disabled=not (job_id and uploads)):
    progress = st.progress(0, text="Starting pipeline...")
    results: list[tuple[str, dict]] = []
    for index, upload in enumerate(uploads):
        try:
            progress.progress(index / len(uploads), text=f"Processing {upload.name}...")
            result = run_pipeline(
                upload.name,
                upload.getvalue(),
                job_id,
                notification_email=notification_email or None,
                job_api_url=job_api_url or None,
                api_key=api_key or None,
                credential_api_url=credential_api_url or None,
                institution_api_url=institution_api_url or None,
            )
            save_artifacts(result, OUTPUT_DIR, Path(upload.name).stem)
            results.append((upload.name, result))
        except (ValueError, OSError) as exc:
            st.error(f"{upload.name}: {exc}")
    progress.progress(1.0, text="Completed")

    for filename, result in results:
        st.divider()
        st.subheader(filename)
        scoring = result["scoring"]
        verification = result["verification"]
        cols = st.columns(3)
        score_value = scoring.get("score")
        cols[0].metric("Match score", "No score" if score_value is None else f"{score_value}%")
        cols[1].metric("Rating", str(scoring.get("rating") or "review").replace("_", " ").title())
        cols[2].metric("Verification", verification["overall_status"].replace("_", " ").title())
        rag_info = scoring.get("rag") or {}
        if rag_info.get("status") != "used":
            st.warning(
                f"Scoring did not use the job's rubric (RAG status: "
                f"{rag_info.get('status', 'unknown')}). {rag_info.get('error') or ''}"
            )
        tabs = st.tabs(["Resume parser", "Verification", "Scoring", "JSON"])
        with tabs[0]:
            st.json(result["resume_parser"])
        with tabs[1]:
            st.json(result["verification"])
        with tabs[2]:
            if scoring.get("rationale"):
                st.text(scoring["rationale"])
            if scoring.get("flags"):
                st.warning("Flags: " + ", ".join(scoring["flags"]))
            if scoring.get("criteria"):
                st.dataframe(
                    [
                        {
                            "id": c["id"],
                            "type": c["type"],
                            "verdict": c["verdict"],
                            "evidence check": c.get("evidence_check"),
                            "requirement": c["requirement"],
                        }
                        for c in scoring["criteria"]
                    ],
                    hide_index=True,
                )
            st.json(result["scoring"])
        with tabs[3]:
            st.json(result)
        st.caption(f"Stage JSON artifacts saved to `{OUTPUT_DIR}`")
