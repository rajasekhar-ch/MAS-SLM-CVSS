"""Local FastAPI simulation for the HR and job-description APIs.

Run from the repository root:
    uvicorn Simulations.api:app --reload --port 8000
"""

from typing import Any

import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query


app = FastAPI(title="CyberSec HR Simulation APIs", version="1.0.0")
API_KEY = os.getenv("SIMULATION_API_KEY", "dev-api-key")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Valid X-API-Key header required")

# Job postings served by /jobs/{job_id}: the study jobs (real postings,
# DJ-201..DJ-210) from scoring_rubrics/study_jobs.json, a JSON object of
# {job_id: {"job_id", "title", "category", "description", ...}}.
# Override the location with JOBS_FILE.
_JOBS_FILE = os.getenv(
    "JOBS_FILE",
    os.path.join(os.path.dirname(__file__), "..", "scoring_rubrics", "study_jobs.json"),
)
JOBS: dict[str, dict[str, Any]] = {}
if os.path.exists(_JOBS_FILE):
    with open(_JOBS_FILE, encoding="utf-8") as _f:
        JOBS = {job_id.upper(): job for job_id, job in json.load(_f).items()}

CERTIFICATIONS = [
    {
        "holder_name": "R Mukesh",
        "certification_name": "CBAP",
        "issuer": "IIBA",
        "certificate_id": "CBAP-2021-04471",
        "issue_date": "2021-03-15",
        "expiry_date": "2026-03-15",
        "status": "active",
    },
    {
        "holder_name": "Daniel Okafor",
        "certification_name": "CompTIA Network+",
        "issuer": "CompTIA",
        "certificate_id": "N10-2019-88213",
        "issue_date": "2019-07-01",
        "expiry_date": "2022-07-01",
        "status": "expired",
    },
]


@app.get("/certifications")
def get_certification(
    certificate_id: str | None = Query(default=None),
    name: str | None = Query(default=None),
    certification_name: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    if certificate_id:
        cert_id_value = certificate_id.strip().lower()
        match = next(
            (c for c in CERTIFICATIONS if c["certificate_id"].lower() == cert_id_value),
            None,
        )
    else:
        name_value = (name or "").strip().lower()
        cert_value = (certification_name or "").strip().lower()
        match = next(
            (
                c for c in CERTIFICATIONS
                if (name_value and c["holder_name"].lower() == name_value)
                and (
                    not cert_value
                    or cert_value in c["certification_name"].lower()
                    or c["certification_name"].lower() in cert_value
                )
            ),
            None,
        )
    if not match:
        return {
            "found": False,
            "certificate_id": certificate_id,
            "name": name,
            "certification_name": certification_name,
            "status": "not_found",
        }
    return {"found": True, **match}


INSTITUTIONS = [
    {
        "name": "University of Plymouth",
        "aliases": ["Plymouth University"],
        "type": "university",
        "country": "UK",
        "status": "verified",
    },
    {
        "name": "Stanford University",
        "aliases": [],
        "type": "university",
        "country": "US",
        "status": "verified",
    },
    {
        "name": "Trident International University",
        "aliases": ["Trident Int'l University"],
        "type": "university",
        "country": "unknown",
        "status": "flagged",
    },
]


@app.get("/institutions")
def get_institution(
    name: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    name_value = (name or "").strip().lower()
    match = next(
        (
            i for i in INSTITUTIONS
            if name_value == i["name"].lower()
            or name_value in [a.lower() for a in i["aliases"]]
        ),
        None,
    )
    if not match:
        return {"found": False, "name": name, "status": "not_found"}
    return {"found": True, **match}


EMPLOYEES = [
    {
        "name": "R Mukesh",
        "phone": "+91-7010223993",
        "email": "jiomukesh95@gmail.com",
        "found": True,
        "previous_employers": [{"company": "Secure Systems Ltd", "title": "Security Analyst"}],
        "status": "review",
    },
    {
        "name": "Sample Candidate",
        "phone": "+1-555-0100",
        "email": "sample@example.com",
        "found": False,
        "previous_employers": [],
        "status": "clear",
    },
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    job = JOBS.get(job_id.upper())
    if not job:
        raise HTTPException(status_code=404, detail=f"Unknown job ID: {job_id}")
    return job


@app.get("/employees")
def get_employee(
    name: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    name_value = (name or "").strip().lower()
    phone_value = (phone or "").strip()
    match = next(
        (
            employee
            for employee in EMPLOYEES
            if (name_value and employee["name"].lower() == name_value)
            or (phone_value and employee["phone"] == phone_value)
        ),
        None,
    )
    if not match:
        return {
            "found": False,
            "name": name,
            "phone": phone,
            "previous_employers": [],
            "status": "clear",
        }
    return match
