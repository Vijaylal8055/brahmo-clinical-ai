"""Hybrid-style retrieval over a local verified-live demo corpus.

Lexical search only (no external embeddings required for Community Cloud).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

SOURCE_REGISTRY = {
    "demo_source_versioning.md": {
        "source_id": "demo-guideline-v3",
        "title": "Demo Clinical Reference (fictional)",
        "issuer": "Synthetic Example Issuer",
        "edition": "3",
        "effective_from": "2026-02-01",
        "jurisdiction": "India (demo)",
        "population_scope": "adults; pediatric excluded",
        "status": "verified-live",
        "rights_status": "approved-for-demo-index-and-display",
    },
    "demo_assessment_workflow.md": {
        "source_id": "demo-workflow-assessment",
        "title": "Demo Assessment Section Workflow (fictional)",
        "issuer": "Synthetic Example Issuer",
        "edition": "1",
        "effective_from": "2026-01-15",
        "jurisdiction": "India (demo)",
        "population_scope": "adults",
        "status": "verified-live",
        "rights_status": "approved-for-demo-index-and-display",
    },
}


def _load_corpus() -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    if not KNOWLEDGE_DIR.exists():
        return chunks
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        meta = SOURCE_REGISTRY.get(
            path.name,
            {
                "source_id": path.stem,
                "title": path.stem,
                "issuer": "unknown",
                "edition": "?",
                "effective_from": None,
                "jurisdiction": "demo",
                "population_scope": "unspecified",
                "status": "verified-live",
                "rights_status": "demo-only",
            },
        )
        current_heading = path.stem
        buffer: List[str] = []
        start_line = 1
        for i, line in enumerate(lines, start=1):
            if line.startswith("#"):
                if buffer:
                    chunks.append(_make_chunk(path.name, meta, current_heading, buffer, start_line, i - 1))
                current_heading = line.lstrip("#").strip() or current_heading
                buffer = [line]
                start_line = i
            else:
                buffer.append(line)
        if buffer:
            chunks.append(_make_chunk(path.name, meta, current_heading, buffer, start_line, len(lines)))
    return chunks


def _make_chunk(filename, meta, heading, lines, start, end):
    body = "\n".join(lines).strip()
    return {
        "chunk_id": f"{filename}:{start}-{end}",
        "filename": filename,
        "heading": heading,
        "text": body,
        "line_start": start,
        "line_end": end,
        **meta,
    }


def _tokenize(q: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", q.casefold()) if len(t) > 2]


def search_knowledge(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    return search_evidence(query, top_k=top_k)


def search_evidence(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    corpus = _load_corpus()
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for chunk in corpus:
        if chunk.get("status") != "verified-live":
            continue
        text_cf = chunk["text"].casefold()
        hits = sum(1 for t in tokens if t in text_cf)
        if hits == 0:
            continue
        score = hits / len(tokens)
        if any(t in chunk["heading"].casefold() for t in tokens):
            score += 0.25
        scored.append((score, chunk))
    scored.sort(key=lambda x: (-x[0], x[1]["filename"], x[1]["line_start"]))
    results = []
    for score, chunk in scored[:top_k]:
        item = dict(chunk)
        item["score"] = round(score, 3)
        results.append(item)
    return results


def evidence_sufficiency_gate(query, evidence, *, require_population=None):
    if not evidence:
        return {"sufficient": False, "reason": "No verified-live evidence matched the query terms.", "action": "abstain"}
    applicable, conflicts = [], []
    for e in evidence:
        scope = (e.get("population_scope") or "").casefold()
        if require_population:
            req = require_population.casefold()
            if req == "pediatric" and "pediatric excluded" in scope:
                conflicts.append(e)
                continue
            if req == "adult" and "pediatric" in scope and "adult" not in scope:
                conflicts.append(e)
                continue
        applicable.append(e)
    if not applicable and conflicts:
        return {
            "sufficient": False,
            "reason": "Retrieved evidence population scope does not match the question.",
            "action": "abstain",
            "conflicts": [{"chunk_id": c["chunk_id"], "population_scope": c.get("population_scope")} for c in conflicts],
        }
    if not applicable:
        return {"sufficient": False, "reason": "No applicable evidence after scope filters.", "action": "abstain"}
    return {
        "sufficient": True,
        "reason": f"{len(applicable)} applicable chunk(s) with verified-live status.",
        "action": "compose",
        "applicable_count": len(applicable),
    }


def compose_grounded_answer(query, evidence, gate):
    if not gate.get("sufficient"):
        return {
            "answer": (
                "I cannot confirm an answer from the verified-live demo corpus for this question. "
                f"Reason: {gate.get('reason', 'insufficient evidence')}."
            ),
            "claims": [],
            "abstained": True,
            "citations": [],
            "coverage_state": "insufficient_evidence",
        }
    citations, claim_parts = [], []
    for e in evidence[:3]:
        excerpt = e["text"][:400].strip()
        if len(e["text"]) > 400:
            excerpt += "…"
        cite = {
            "source_id": e.get("source_id"),
            "title": e.get("title"),
            "issuer": e.get("issuer"),
            "edition": e.get("edition"),
            "effective_from": e.get("effective_from"),
            "filename": e.get("filename"),
            "line_start": e.get("line_start"),
            "line_end": e.get("line_end"),
            "heading": e.get("heading"),
            "excerpt": excerpt,
        }
        citations.append(cite)
        claim_parts.append(
            f"From {e.get('title')} ({e.get('issuer')}, edition {e.get('edition')}, "
            f"effective {e.get('effective_from')}, {e.get('filename')} lines "
            f"{e.get('line_start')}–{e.get('line_end')}):\n> {excerpt}"
        )
    answer = (
        f"**Demo grounded response** for: “{query}”\n\n"
        + "\n\n".join(claim_parts)
        + "\n\n---\n"
        "*This is a lexical excerpt from a fictional demo corpus. "
        "It is not clinical guidance and must not be used for patient care.*"
    )
    claims = [
        {
            "text": f"Excerpt from {c['title']} section “{c['heading']}”",
            "supported_by": f"{c['filename']}:{c['line_start']}-{c['line_end']}",
            "validated": True,
        }
        for c in citations
    ]
    return {
        "answer": answer,
        "claims": claims,
        "abstained": False,
        "citations": citations,
        "coverage_state": "grounded_demo",
    }
