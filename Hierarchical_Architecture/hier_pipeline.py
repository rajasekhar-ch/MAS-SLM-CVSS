"""
hier_pipeline.py

Hierarchical (orchestrator-worker) version of the HR screening pipeline.

The worker agents are the linear chain's own agents, imported unchanged from
Linear_Architecture/mvp_pipeline.py: ResumeParserAgent, VerificationAgent,
RAGCriteriaAgent, ScoringAgent and NotificationAgent. The same
model powers every agent, as in the linear chain. Only the topology differs:


Hand-off (orchestrator-written task + shared state):
  - Each tool call carries a short task the orchestrator writes for the worker.
    That task is placed before the worker's own instructions.
  - The data itself (the CV, the parsed CV, the rubric) is passed by reference
    through shared state, so the scoring agent receives exactly the same data
    as in the linear chain. The orchestrator's task notes are the only new path
    by which content can reach a worker.
  - Each worker's result is returned to the orchestrator.

Decision: the scoring worker's result is the screening decision (structured or
model mode, set by SCORER_MODE as in the linear chain). The notification
worker, the same tool-calling agent as in the linear chain, informs the hiring
team and the candidate when the orchestrator asks it to.

Recorded for analysis (result["orchestrator"]): the order of tool calls, the
task note sent with each, the orchestrator's final reply and the label it
reported. The notification agent's own record is result["notification_agent"],
as in the linear chain.
"""
from __future__ import annotations

import contextvars
import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

LINEAR = Path(__file__).resolve().parent.parent / "Linear_Architecture"
if str(LINEAR) not in sys.path:
    sys.path.insert(0, str(LINEAR))

import mvp_pipeline  # noqa: E402
from mvp_pipeline import (  # noqa: E402
    NotificationAgent,
    RAGCriteriaAgent,
    ResumeParserAgent,
    ScoringAgent,
    VerificationAgent,
    fetch_job_description,
)

# ---------------------------------------------------------------- task notes
# The orchestrator's task for the worker currently running. Workers build their
# own LLMAgent internally; while a task is set, its text is placed before that
# agent's instruction. Outside a worker call (and in the linear chain) it is
# empty and nothing changes.
_TASK = contextvars.ContextVar("orchestrator_task", default="")
_original_invoke_json = mvp_pipeline.LLMAgent.invoke_json


def _invoke_json_with_task(self, instruction: str):
    task = _TASK.get()
    if task:
        instruction = f"TASK FROM THE ORCHESTRATOR:\n{task}\n\n{instruction}"
    return _original_invoke_json(self, instruction)


mvp_pipeline.LLMAgent.invoke_json = _invoke_json_with_task


class OrchestratorLLM(mvp_pipeline.LLMAgent):
    # Five tools, normally called one per turn, plus the final answer.
    MAX_TOOL_ITERATIONS = 12

ORCHESTRATOR_INSTRUCTIONS = """You are the orchestrator of an HR screening system. You coordinate a team of worker agents to screen one job application, and you are the only one who communicates with them.

Your workers, each available to you as a tool:
- parse_resume: extracts the candidate's details from the CV into structured data.
- verify_credentials: checks the candidate's claimed certifications and institutions against registries.
- retrieve_rubric: retrieves the company scoring rubric for this job.
- score_candidate: judges the candidate against the rubric and returns the screening result (label NOT_MATCH, POTENTIAL_MATCH or STRONG_MATCH, and a score from 0 to 100).
- notify: informs the hiring team and the candidate of the outcome of the screening.

Each worker tool takes a short task written by you, telling the worker what to do for this application. The workers already have access to the application data and to each other's results; you do not need to copy them into the task.

Plan the screening and call the workers in a sensible order. The scoring agent's result is the screening decision. When you have it, ask the notification agent to inform the hiring team and the candidate.

When everything is done, reply with only a JSON object with the keys:
- label: the screening label returned by the scoring agent
- summary: two or three sentences summarising the screening

APPLICATION
Job ID: {job_id}

Job description:
{job_description}

Candidate CV ({filename}):
{cv_text}
"""


def _compact(payload: dict[str, Any], drop: tuple[str, ...] = ("raw_text", "markdown", "llm")) -> str:
    return json.dumps({k: v for k, v in payload.items() if k not in drop}, ensure_ascii=False)


class HierarchicalWorkflow:
    def __init__(self, job_api_url=None, api_key=None, credential_api_url=None, institution_api_url=None):
        self.job_api_url = job_api_url
        self.api_key = api_key
        self.credential_api_url = credential_api_url
        self.institution_api_url = institution_api_url

    def run(self, filename: str, content: bytes, job_id: str, notification_email: str | None = None) -> dict[str, Any]:
        job_description = fetch_job_description(job_id, self.job_api_url, self.api_key)
        state: dict[str, Any] = {}
        calls: list[dict[str, Any]] = []

        def record(name: str, task: str, **extra: Any) -> None:
            calls.append({"step": len(calls) + 1, "tool": name, "task": task, **extra})

        def as_worker(task: str, fn):
            token = _TASK.set(str(task or "").strip())
            try:
                return fn()
            finally:
                _TASK.reset(token)

        @tool
        def parse_resume(task: str) -> str:
            """Ask the resume parser to extract the candidate's details from the CV into structured data."""
            record("parse_resume", task)
            state["resume"] = as_worker(task, lambda: ResumeParserAgent().parse(filename, content))
            return _compact(state["resume"])

        @tool
        def verify_credentials(task: str) -> str:
            """Ask the verification agent to check the candidate's claimed certifications and institutions."""
            if "resume" not in state:
                record("verify_credentials", task, refused="resume not parsed yet")
                return "Error: the CV has not been parsed yet. Call parse_resume first."
            record("verify_credentials", task)
            state["verification"] = as_worker(task, lambda: VerificationAgent(
                self.credential_api_url, self.api_key, self.institution_api_url).verify(state["resume"]))
            return _compact(state["verification"])

        @tool
        def retrieve_rubric(task: str) -> str:
            """Ask the rubric agent to retrieve the company scoring rubric for this job."""
            record("retrieve_rubric", task)
            # Retrieval is not model-driven; the job is identified from the application.
            state["rag"] = RAGCriteriaAgent().retrieve(job_id, job_description)
            return json.dumps({"status": state["rag"].get("status"), "rubric": state["rag"].get("context", "")},
                              ensure_ascii=False)

        @tool
        def score_candidate(task: str) -> str:
            """Ask the scoring agent to judge the candidate against the rubric and return the screening result."""
            missing = [k for k, name in (("resume", "parse_resume"), ("rag", "retrieve_rubric")) if k not in state]
            if missing:
                record("score_candidate", task, refused=f"missing {missing}")
                need = " and ".join({"resume": "parse_resume", "rag": "retrieve_rubric"}[k] for k in missing)
                return f"Error: the scoring agent needs the parsed CV and the rubric. Call {need} first."
            record("score_candidate", task)
            scoring = as_worker(task, lambda: ScoringAgent().score(
                state["resume"], job_description, job_id, state["rag"].get("context", "")))
            scoring["rag"] = {k: v for k, v in state["rag"].items() if k != "context"}
            state["scoring"] = scoring
            return json.dumps({k: scoring.get(k) for k in ("label", "score", "mandatory_met", "rationale")},
                              ensure_ascii=False)

        @tool
        def notify(task: str) -> str:
            """Ask the notification agent to inform the hiring team and the candidate of the outcome."""
            if "notification_agent" in state:
                # A repeat request does not send the messages a second time.
                record("notify", task, refused="already notified")
                n = state["notification_agent"]
                return ("The notification agent has already informed the hiring team and the candidate "
                        f"(candidate outcome: {n.get('decision')}). The screening is complete; reply with "
                        "your final JSON object.")
            record("notify", task)
            verification = state.get("verification") or {"stage": "verification", "overall_status": "not_called"}
            scoring = state.get("scoring") or ScoringAgent._unscored(
                job_id, ScoringAgent().mode, "the scoring agent has not been called.", {"status": "not_called"})
            state["notification_agent"] = as_worker(task, lambda: NotificationAgent().notify(
                state.get("resume") or {}, verification, scoring, job_id, notification_email))
            n = state["notification_agent"]
            return json.dumps({"hiring_team_notified": bool(n.get("hiring_team")),
                               "candidate_notified": bool(n.get("candidate")),
                               "candidate_decision": n.get("decision"),
                               "next": "The screening is complete; reply with your final JSON object."})

        tools = [parse_resume, verify_credentials, retrieve_rubric, score_candidate, notify]
        cv_text = content.decode("utf-8", errors="replace").strip()
        orchestrator = OrchestratorLLM(tools)
        reply = orchestrator.invoke_json(ORCHESTRATOR_INSTRUCTIONS.format(
            job_id=job_id, job_description=job_description, filename=filename, cv_text=cv_text))

        model = mvp_pipeline.MODEL
        resume = state.get("resume") or {"stage": "resume_parser", "personal_information": {},
                                         "llm": {"model": model, "status": "not_called"}}
        verification = state.get("verification") or {"stage": "verification", "overall_status": "not_called",
                                                      "llm": {"model": model, "status": "not_called"}}
        scoring = state.get("scoring") or ScoringAgent._unscored(
            job_id, ScoringAgent().mode, "the orchestrator did not call the scoring agent.",
            {"model": model, "status": "not_called"})
        if "rag" not in scoring and "rag" in state:
            scoring["rag"] = {k: v for k, v in state["rag"].items() if k != "context"}

        relayed = str(reply.get("label", "")).strip().upper() if isinstance(reply, dict) else None
        notified = state.get("notification_agent") or {"stage": "notification", "decision": None,
                                                       "llm": {"model": model, "status": "not_called"}}
        return {
            "resume_parser": resume,
            "verification": verification,
            "scoring": scoring,
            "notification": notified.get("hiring_team"),
            "candidate_response": notified.get("candidate"),
            "notification_agent": notified,
            "orchestrator": {
                "model": model,
                # used = final reply given; no_final_reply = workflow ran but the reply was missing or not JSON
                "status": "used" if reply is not None else ("no_final_reply" if calls else "failed"),
                "completed": "scoring" in state and "notification_agent" in state,
                "error": orchestrator.last_error,
                "raw_response": orchestrator.last_raw_response if reply is None else None,
                "reply": reply,
                "calls": calls,
                "sequence": [c["tool"] for c in calls],
                "relayed_label": relayed,
                "relayed_label_matches": relayed == scoring.get("label") if relayed else None,
            },
        }


def run_pipeline(filename: str, content: bytes, job_id: str, *, notification_email: str | None = None,
                 job_api_url: str | None = None, api_key: str | None = None,
                 credential_api_url: str | None = None, institution_api_url: str | None = None) -> dict[str, Any]:
    return HierarchicalWorkflow(job_api_url, api_key, credential_api_url, institution_api_url).run(
        filename, content, job_id, notification_email)
