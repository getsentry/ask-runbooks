"""
Ingest: chunk, embed, and upsert documents into postgres.

Flow:
    Document → chunks → embeddings → postgres

Change detection:
    Each document stores a SHA-256 hash of its content.
    On re-index, unchanged docs are skipped entirely — no re-embedding needed.
    Changed docs delete their old chunks (CASCADE) and re-insert.

Markdown chunking strategy:
    1. Split on H1/H2 markdown headers — each section becomes a candidate chunk.
    2. If a section is too long, split further on H3 headers or paragraph breaks.
    3. Prepend the document title to every chunk so each chunk has context
       even when read in isolation.

Chunk size:
    MAX_CHARS = 1500 chars ≈ 350-400 tokens (rough: 1 token ≈ 4 chars).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .db import dict_cursor
from .embeddings import embed
from .sources.base import Document

MAX_CHARS = 1500


@dataclass
class Chunk:
    content: str
    chunk_index: int


def chunk_markdown(content: str, title: str = "") -> list[Chunk]:
    """Split a markdown document into indexable chunks."""
    sections = re.split(r"(?=\n#{1,2} )", content.strip())
    sections = [s.strip() for s in sections if s.strip()]

    raw_chunks: list[str] = []
    prefix = f"# {title}\n\n" if title else ""

    for section in sections:
        if len(section) <= MAX_CHARS:
            raw_chunks.append(section)
        else:
            subsections = re.split(r"(?=\n### |\n\n)", section)
            current = ""
            for sub in subsections:
                if current and len(current) + len(sub) > MAX_CHARS:
                    raw_chunks.append(current.strip())
                    current = sub
                else:
                    current = current + sub if current else sub
            if current.strip():
                raw_chunks.append(current.strip())

    return [
        Chunk(content=f"{prefix}{c}" if prefix else c, chunk_index=i)
        for i, c in enumerate(raw_chunks)
        if c.strip()
    ]


def extract_title(content: str, fallback: str = "") -> str:
    """Extract the first H1 heading, or fall back to filename."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def extract_incident_fields(content: str) -> dict:
    """Extract severity, date, and INC number from the header area of an incident doc."""
    header = content[:2000]
    fields = {}
    severity = re.search(r"(?i)severity[^\n]*?(P[0-4])", header)
    if severity:
        fields["severity"] = severity.group(1)
    date = re.search(r"(?i)(?:inc\s+)?date[^\n]*?(\b\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", header)
    if date:
        fields["inc_date"] = date.group(1).strip()
    inc_number = re.search(r"\bINC-(\d+)\b", content)
    if inc_number:
        fields["inc_number"] = f"INC-{inc_number.group(1)}"
    return fields


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def ingest_documents(conn, documents: list[Document]) -> dict[str, int]:
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "chunks": 0}

    for doc in documents:
        content_hash = _hash(doc.content)

        with dict_cursor(conn) as cur:
            cur.execute(
                "SELECT id, hash FROM documents WHERE source = %s AND path = %s",
                (doc.source, doc.path),
            )
            existing = cur.fetchone()

        if existing and existing["hash"] == content_hash:
            stats["skipped"] += 1
            continue

        chunks = chunk_markdown(doc.content, title=doc.title)
        if not chunks:
            continue

        texts = [c.content for c in chunks]
        vectors = embed(texts)

        with dict_cursor(conn) as cur:
            if existing:
                cur.execute(
                    """
                    UPDATE documents SET title=%s, content=%s, hash=%s, synced_at=NOW(), metadata=%s
                    WHERE id=%s RETURNING id
                    """,
                    (doc.title, doc.content, content_hash,
                     _json(doc.metadata), existing["id"]),
                )
                doc_id = existing["id"]
                cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
                stats["updated"] += 1
            else:
                cur.execute(
                    """
                    INSERT INTO documents (source, doc_type, path, title, content, hash, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (doc.source, doc.doc_type, doc.path, doc.title,
                     doc.content, content_hash, _json(doc.metadata)),
                )
                doc_id = cur.fetchone()["id"]
                stats["inserted"] += 1

            for chunk, vector in zip(chunks, vectors):
                cur.execute(
                    """
                    INSERT INTO chunks (document_id, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (doc_id, chunk.chunk_index, chunk.content, vector),
                )
                stats["chunks"] += 1

        conn.commit()

    return stats


def _json(d: dict) -> str:
    import json
    return json.dumps(d)
