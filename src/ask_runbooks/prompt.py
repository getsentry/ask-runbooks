"""
Q&A: send retrieved chunks + question to an LLM, return a grounded answer.

Supports Claude (via Anthropic SDK) and Ollama (local models, no API cost).
Configure in config.yaml:

    llm:
      provider: claude          # or: ollama
      model: claude-sonnet-4-6  # or e.g. llama3.2
      ollama_url: http://localhost:11434  # only for ollama
"""

from __future__ import annotations

import re

from .llm import LLMProvider
from .types import Message
from .search import SearchResult


def _parse_glossary(context_note: str) -> dict[str, str]:
    """Parse '- TERM: Definition' lines into a dict."""
    terms = {}
    for line in context_note.splitlines():
        m = re.match(r"[-*]?\s*([A-Z][A-Z0-9]+):\s*(.+)", line.strip())
        if m:
            terms[m.group(1)] = m.group(2).strip()
    return terms


def expand_acronyms(text: str, glossary: dict[str, str]) -> str:
    """Replace bare acronyms in text with 'ACRONYM (Definition)'."""
    for term, definition in glossary.items():
        text = re.sub(
            rf"\b{re.escape(term)}\b(?!\s*\()",
            f"{term} ({definition})",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    return text


def _build_context(results: list[SearchResult]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        meta = []
        if r.metadata.get("inc_date"):
            meta.append(r.metadata["inc_date"])
        if r.metadata.get("severity"):
            meta.append(r.metadata["severity"])
        suffix = f" ({', '.join(meta)})" if meta else ""
        label = f"[{i}] {r.doc_type.upper()} — {r.title}{suffix}"
        parts.append(f"{label}\n{r.content}")
    return "\n\n---\n\n".join(parts)


def _system_prompt(results: list[SearchResult], context_note: str = "") -> str:
    context = _build_context(results)
    glossary = f" When using internal terms, always use these exact definitions and never invent alternatives:\n{context_note}" if context_note else ""
    if results:
        doc_types = sorted({r.doc_type for r in results})
        label = " and ".join(doc_types)
        docs = f"\n\nYou have been given the following {label} records from Sentry's internal knowledge base. Answer based on these:\n\n{context}"
    else:
        docs = ""
    return f"""You are a helpful assistant for engineers at Sentry.{glossary}{docs}

Be concise. If you don't have enough information, say so briefly. Do not invent sources."""


def answer_in_session(
    question: str,
    results: list[SearchResult],
    history: list[Message],
    llm: LLMProvider,
    context_note: str = "",
) -> str:
    if context_note:
        glossary = _parse_glossary(context_note)
        question = expand_acronyms(question, glossary)
    system = _system_prompt(results, context_note)
    messages = history + [{"role": "user", "content": question}]
    return llm.ask(system, messages)
