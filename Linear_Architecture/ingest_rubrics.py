"""
ingest_rubrics.py

Builds the rubric FAISS index. Each rubric PDF is split into one chunk per
rubric section (SCORE SCALE, MANDATORY REQUIREMENT, PREFERRED CRITERIA, BASIS),
so a rule and its score cap always stay together.
"""

import hashlib
import os
import pickle
import re
from pathlib import Path

import faiss
import fitz
import numpy as np
import ollama

MODULE_DIR = Path(__file__).resolve().parent
ROOT = MODULE_DIR.parent
RUBRIC_FOLDER = ROOT / "scoring_rubrics"
# Written next to this file (not the current directory) so rag_criteria_agent.py
# always finds them, wherever this script is run from.
FAISS_INDEX_PATH = MODULE_DIR / "rubric_faiss.index"
METADATA_PATH = MODULE_DIR / "rubric_metadata.pkl"
EMBEDDING_MODEL = "qllama/bge-small-en-v1.5:latest"

# A section longer than this is split on line boundaries.
MAX_SECTION_CHARS = 1500

JOB_ID_RE = re.compile(r"Job ID:\s*([A-Za-z]{2,}-\d+)")
# A section heading is an all-caps line, optionally followed by a bracketed
# note, e.g. "MANDATORY REQUIREMENT (non-compensatory minimum qualifications)".
HEADING_RE = re.compile(r"^[A-Z][A-Z &/\-]{4,}(?:\s*\(.*)?$")


def extract_pdf_pages(pdf_path):
    pages = []
    pdf = fitz.open(pdf_path)
    try:
        for page_number, page in enumerate(pdf):
            text = page.get_text("text")
            if text and text.strip():
                pages.append({"text": text, "page": page_number + 1})
    finally:
        pdf.close()
    return pages


def _heading_label(line):
    """'MANDATORY REQUIREMENT (non-...)' -> 'mandatory requirement'."""
    return line.split("(", 1)[0].strip().lower()


def _split_long(lines, limit):
    """Group lines into parts no longer than `limit` characters."""
    parts, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) + 1 > limit:
            parts.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append(current)
    return parts


def parse_rubric_sections(pages, source, doc_sha256=""):
    """Split one rubric document into section chunks.

    Returns a list of dicts with: text, source, page, chunk, section, job_id,
    doc_sha256. job_id is None for a document that does not state one (for
    example a shared methodology note); those chunks are treated as shared
    knowledge rather than belonging to one role.
    """
    lines = []  # (page, line)
    for page in pages:
        for raw in page["text"].splitlines():
            line = raw.strip()
            if line:
                lines.append((page["page"], line))
    if not lines:
        return []

    full_text = "\n".join(line for _, line in lines)
    match = JOB_ID_RE.search(full_text)
    job_id = match.group(1).upper() if match else None

    title = lines[0][1]
    sections = []  # (label, page, [lines])
    current_label, current_page, current_lines = "overview", lines[0][0], []
    for page_number, line in lines[1:]:
        if HEADING_RE.match(line):
            if current_lines:
                sections.append((current_label, current_page, current_lines))
            current_label, current_page, current_lines = _heading_label(line), page_number, [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_label, current_page, current_lines))

    chunks = []
    for label, page_number, body in sections:
        heading = body[0] if HEADING_RE.match(body[0]) else None
        for part_number, part in enumerate(_split_long(body, MAX_SECTION_CHARS)):
            # The title line is repeated in every chunk so each one says which
            # role it belongs to when read on its own.
            text = title + "\n" + "\n".join(part)
            if part_number > 0 and heading:
                text = title + "\n" + heading + "\n" + "\n".join(part)
            chunks.append({
                "text": text,
                "source": source,
                "page": page_number,
                "chunk": len(chunks),
                "section": label if part_number == 0 else f"{label} (part {part_number + 1})",
                "job_id": job_id,
                "doc_sha256": doc_sha256,
            })
    return chunks


def generate_embedding(text):
    response = ollama.embed(model=EMBEDDING_MODEL, input=text)
    embedding = response.embeddings[0]
    embedding = np.asarray(embedding, dtype=np.float32).flatten()
    if embedding.ndim != 1:
        raise ValueError(f"Invalid embedding shape: {embedding.shape}")
    if embedding.shape[0] != 384:
        raise ValueError(
            f"Unexpected embedding dimension: {embedding.shape[0]}. Expected 384 for bge-small-en-v1.5."
        )
    return embedding


def process_rubrics():
    all_chunks = []
    if not os.path.exists(RUBRIC_FOLDER):
        raise FileNotFoundError(f"Rubric folder not found: {os.path.abspath(RUBRIC_FOLDER)}")
    pdf_files = sorted(f for f in os.listdir(RUBRIC_FOLDER) if f.lower().endswith(".pdf"))
    print(f"Found {len(pdf_files)} rubric PDF(s).")
    for pdf_file in pdf_files:
        pdf_path = os.path.join(RUBRIC_FOLDER, pdf_file)
        print(f"\nProcessing: {pdf_file}")
        with open(pdf_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        chunks = parse_rubric_sections(extract_pdf_pages(pdf_path), pdf_file, digest)
        job_ids = {c["job_id"] for c in chunks}
        print(f"  job_id={sorted(str(j) for j in job_ids)} sections={[c['section'] for c in chunks]}")
        all_chunks.extend(chunks)
    sources_by_job = {}
    for chunk in all_chunks:
        if chunk["job_id"]:
            sources_by_job.setdefault(chunk["job_id"], set()).add(chunk["source"])
    for job, sources in sorted(sources_by_job.items()):
        if len(sources) > 1:
            print(f"WARNING: job_id {job} appears in more than one rubric: {sorted(sources)}")
    print(f"\nCreated {len(all_chunks)} chunks.")
    return all_chunks


def create_faiss_index(chunks):
    embeddings, metadata = [], []
    for i, chunk in enumerate(chunks):
        print(f"Embedding {i + 1}/{len(chunks)} ({chunk['source']} - {chunk['section']})")
        embeddings.append(generate_embedding(chunk["text"]))
        metadata.append(chunk)
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim != 2 or embeddings.shape[1] != 384:
        raise ValueError(f"Invalid embeddings shape: {embeddings.shape}. Expected (n, 384).")
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, str(FAISS_INDEX_PATH))
    with open(METADATA_PATH, "wb") as f:
        pickle.dump(metadata, f)
    print(f"\nSaved: {FAISS_INDEX_PATH}, {METADATA_PATH}")
    print(f"Index contains {index.ntotal} vectors.")


if __name__ == "__main__":
    print("=" * 60)
    print("RUBRIC EMBEDDING / FAISS INGESTION")
    print("=" * 60)
    try:
        test_embedding = generate_embedding("This is a test sentence.")
        print(f"Ollama embedding test successful. Shape: {test_embedding.shape}")
    except Exception as e:
        print("ERROR: Could not generate embedding.")
        print(f"Make sure Ollama is running and '{EMBEDDING_MODEL}' is installed.")
        print(f"Details: {e}")
        raise

    chunks = process_rubrics()
    if not chunks:
        print("No text found in rubric PDFs.")
        raise SystemExit(0)
    create_faiss_index(chunks)
    print("\nIngestion completed successfully!")
