"""
rag_criteria_agent.py

The RAG grounding step for ScoringAgent. For a given job it fetches that role's
scoring rubric and formats it into a context block for ScoringAgent's prompt.

Retrieval works in two parts:
  1. The rubric for the job is looked up directly by job_id and ALWAYS included
     (its mandatory requirements and score caps must not depend on similarity).
  2. Chunks that belong to no particular role (job_id is None, e.g. a shared
     methodology or policy note) are ranked by similarity to the job
     description and added if they clear the similarity threshold.

Rubrics for other roles are never retrieved. The result carries a status, so a
missing index, an out-of-date index, or a job with no rubric is visible in the
output instead of silently producing an ungrounded score.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import Any

import faiss

from config import MAX_CONTEXT_CHARS, SIMILARITY_THRESHOLD, TOP_K

# Resolved against this file's own directory, not the process's current
# working directory, so the paths are correct regardless of where the
# Streamlit app (or any other entry point) was launched from.
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
RUBRIC_FAISS_INDEX_PATH = os.path.join(_MODULE_DIR, "rubric_faiss.index")
RUBRIC_METADATA_PATH = os.path.join(_MODULE_DIR, "rubric_metadata.pkl")


class IndexOutdatedError(ValueError):
    """The index was built by an older ingest_rubrics.py (no job_id/section)."""


def _norm(job_id: Any) -> str:
    return str(job_id or "").strip().upper()


@dataclass
class RAGCriteriaAgent:
    """Fetches grounding context for ScoringAgent from the rubric index.

    status values returned by retrieve():
      used               the job's rubric was found and included
      no_rubric_for_job  the index has no rubric for this job_id
      fallback           no rubric for the job; similarity search across all
                         rubrics was used because semantic_fallback is on
      unavailable        index or metadata file missing
      index_outdated     index built by an older ingest; re-run ingest_rubrics.py
      error              anything else (see "error")
    """

    index_path: str = RUBRIC_FAISS_INDEX_PATH
    metadata_path: str = RUBRIC_METADATA_PATH
    top_k: int = TOP_K
    # Off by default: a job with no rubric gets no rubric, not another role's.
    semantic_fallback: bool = False
    _index: object = field(default=None, init=False, repr=False)
    _metadata: object = field(default=None, init=False, repr=False)

    def _ensure_loaded(self) -> None:
        if self._index is not None:
            return
        if not os.path.exists(self.index_path):
            raise FileNotFoundError(
                f"Rubric FAISS index not found: {os.path.abspath(self.index_path)}. "
                "Run ingest_rubrics.py first."
            )
        if not os.path.exists(self.metadata_path):
            raise FileNotFoundError(
                f"Rubric metadata not found: {os.path.abspath(self.metadata_path)}. "
                "Run ingest_rubrics.py first."
            )
        index = faiss.read_index(self.index_path)
        with open(self.metadata_path, "rb") as f:
            metadata = pickle.load(f)
        if not all(isinstance(m, dict) and "job_id" in m and "section" in m for m in metadata):
            raise IndexOutdatedError(
                "The rubric index was built by an older version of ingest_rubrics.py "
                "(chunks have no job_id/section). Re-run ingest_rubrics.py."
            )
        self._index, self._metadata = index, metadata

    def _rank(self, ids: list[int], query: str, limit: int) -> list[tuple[float, int]]:
        """Similarity-rank the given chunk ids against the query."""
        from chatbot import generate_query_embedding  # lazy: needs Ollama

        query_vector = generate_query_embedding(query)[0]
        scored = []
        for i in ids:
            score = float(query_vector @ self._index.reconstruct(i))
            if score >= SIMILARITY_THRESHOLD:
                scored.append((score, i))
        scored.sort(reverse=True)
        return scored[:limit]

    def retrieve(self, job_id: str, job_description: str) -> dict[str, Any]:
        """Return {"status", "job_id", "context", "chunks", ["error"], ["warnings"]}."""
        result: dict[str, Any] = {
            "status": "used",
            "job_id": job_id,
            "context": "",
            "chunks": [],
        }
        try:
            self._ensure_loaded()
        except FileNotFoundError as e:
            # Fail open so scoring can still run, but say so in the output.
            result.update(status="unavailable", error=str(e))
            return result
        except IndexOutdatedError as e:
            result.update(status="index_outdated", error=str(e))
            return result
        except Exception as e:  # corrupt index/pickle etc.
            result.update(status="error", error=f"{type(e).__name__}: {e}")
            return result

        try:
            metadata = self._metadata
            wanted = _norm(job_id)
            pinned = [i for i, m in enumerate(metadata) if _norm(m.get("job_id")) == wanted and wanted]
            pinned.sort(key=lambda i: metadata[i].get("chunk", i))
            shared = [i for i, m in enumerate(metadata) if not m.get("job_id")]

            entries: list[tuple[dict, str, float | None]] = [
                (metadata[i], "job_id", None) for i in pinned
            ]
            warnings: list[str] = []
            pinned_sources = sorted({str(metadata[i].get("source")) for i in pinned})
            if len(pinned_sources) > 1:
                warnings.append(
                    f"more than one rubric document states job_id {job_id}: "
                    f"{', '.join(pinned_sources)}; all of them were included"
                )
            query = f"scoring rubric and mandatory requirements for job {job_id}: {job_description}"

            if not pinned:
                result["status"] = "no_rubric_for_job"
                if self.semantic_fallback:
                    result["status"] = "fallback"
                    ranked = self._rank(list(range(len(metadata))), query, self.top_k)
                    entries = [(metadata[i], "semantic_fallback", s) for s, i in ranked]
                    if not entries:
                        result["status"] = "no_rubric_for_job"
            elif shared:
                try:
                    entries += [(metadata[i], "similarity", s) for s, i in self._rank(shared, query, self.top_k)]
                except Exception as e:  # e.g. Ollama not running
                    warnings.append(f"shared knowledge not retrieved: {type(e).__name__}: {e}")

            # The job's own rubric is never truncated; shared chunks only fill
            # whatever space is left under MAX_CONTEXT_CHARS.
            parts: list[str] = []
            used_chars = 0
            for meta, selection, score in entries:
                block = f"[RUBRIC {meta.get('source', 'unknown')} | {meta.get('section', '')}]\n{meta.get('text', '')}\n"
                if selection != "job_id" and used_chars + len(block) > MAX_CONTEXT_CHARS:
                    break
                parts.append(block)
                used_chars += len(block)
                result["chunks"].append({
                    "source": meta.get("source"),
                    "section": meta.get("section"),
                    "page": meta.get("page"),
                    "selection": selection,
                    "score": None if score is None else round(score, 4),
                })
            result["context"] = "\n".join(parts)
            if warnings:
                result["warnings"] = warnings
        except Exception as e:
            result.update(status="error", error=f"{type(e).__name__}: {e}", context="", chunks=[])
        return result

    def retrieve_criteria(self, job_id: str, job_description: str) -> str:
        """Context string only (kept for callers that do not need the status)."""
        return self.retrieve(job_id, job_description)["context"]
