"""
rubric_parser.py

Reads the structured parts of a retrieved rubric: the mandatory criteria, the
preferred criteria and the score cap that applies when a mandatory criterion is
not met. The input is the context text produced by RAGCriteriaAgent, so the rubric
that was retrieved is the rubric that is scored against.

Rubric format expected (as produced by scoring_rubrics/build_rubrics.py):

    MANDATORY REQUIREMENT (...)
    <note that states the cap, e.g. "... the score should not exceed 65.">
    - first mandatory criterion
    - second mandatory criterion
    PREFERRED CRITERIA (...)
    - preferred criterion
    ...

Nothing here calls a model. If the rubric cannot be read (no mandatory criteria,
or no cap), parse_rubric returns an error and the scorer reports the candidate
as unscorable instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_BLOCK_RE = re.compile(r"^\[RUBRIC (?P<source>.+?) \| (?P<section>[^\]]*)\]\s*$", re.MULTILINE)
_CAP_RE = re.compile(r"(?:not|never)\s+(?:be\s+)?exceed(?:ing)?\s+(\d{1,3})", re.IGNORECASE)
_HEADING_RE = re.compile(r"^[A-Z][A-Z &/\-]{4,}(?:\s*\(.*)?$")


@dataclass
class Criterion:
    id: str
    kind: str  # "mandatory" or "preferred"
    text: str


@dataclass
class ParsedRubric:
    mandatory: list[Criterion] = field(default_factory=list)
    preferred: list[Criterion] = field(default_factory=list)
    cap: int | None = None
    sources: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def criteria(self) -> list[Criterion]:
        return self.mandatory + self.preferred


def _split_blocks(context: str) -> list[tuple[str, str, str]]:
    """Return (source, section, text) for every [RUBRIC ...] block."""
    matches = list(_BLOCK_RE.finditer(context))
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(context)
        blocks.append((m.group("source"), m.group("section").strip().lower(), context[m.end():end].strip()))
    return blocks


def _bullets_and_note(text: str) -> tuple[list[str], str]:
    """Split a section into its note (text before the first bullet, heading and
    title excluded) and its bullets (wrapped lines are re-joined)."""
    note_lines: list[str] = []
    bullets: list[str] = []
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif bullets:
            bullets[-1] += " " + line  # continuation of a wrapped bullet
        elif index == 0 or _HEADING_RE.match(line):
            continue  # title line or section heading
        else:
            note_lines.append(line)
    return bullets, " ".join(note_lines)


def parse_rubric(context: str) -> ParsedRubric:
    parsed = ParsedRubric()
    if not context or not context.strip():
        parsed.error = "no rubric text to read"
        return parsed

    caps: list[int] = []
    seen_mandatory: set[str] = set()
    seen_preferred: set[str] = set()
    for source, section, text in _split_blocks(context):
        if section.startswith("mandatory requirement"):
            bullets, note = _bullets_and_note(text)
            for cap in _CAP_RE.findall(note):
                caps.append(int(cap))
            for bullet in bullets:
                if bullet not in seen_mandatory:
                    seen_mandatory.add(bullet)
                    parsed.mandatory.append(Criterion(f"M{len(parsed.mandatory) + 1}", "mandatory", bullet))
            parsed.sources.append(source)
        elif section.startswith("preferred criteria"):
            bullets, _ = _bullets_and_note(text)
            for bullet in bullets:
                if bullet not in seen_preferred:
                    seen_preferred.add(bullet)
                    parsed.preferred.append(Criterion(f"P{len(parsed.preferred) + 1}", "preferred", bullet))
            parsed.sources.append(source)

    parsed.sources = sorted(set(parsed.sources))
    if not parsed.mandatory:
        parsed.error = "no mandatory criteria found in the rubric"
    elif not caps:
        parsed.error = "no score cap found in the rubric's mandatory section"
    else:
        # If more than one rubric document supplied a cap, the lowest applies.
        parsed.cap = min(caps)
    return parsed
