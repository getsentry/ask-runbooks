"""
Hybrid search: semantic (vector) + keyword (full-text), fused with Reciprocal Rank Fusion.

Why hybrid?
    Semantic search:  understands meaning, misses exact terms (service names, error codes, versions)
    Keyword search:   matches exact terms, misses paraphrases and synonyms

    Example: query "payments is down"
        Semantic finds: "revenue service outage", "checkout failure runbook" ✓
        Keyword finds:  "payments service restart steps"                     ✓
        Hybrid finds both.

Reciprocal Rank Fusion (RRF):
    A simple, robust way to merge two ranked lists.
    Score = 1/(k + rank_semantic) + 1/(k + rank_keyword)
    where k=60 is a constant that dampens the impact of high ranks.
    No need to normalise scores across the two systems — ranks are always 1..N.

    The SQL below does this entirely in the database — no post-processing needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .db import dict_cursor
from .embeddings import embed_one

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_THRESHOLD = -5.0  # cross-encoder scores are roughly -10 to +10; below this = not relevant
_reranker = None


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        print(f"Loading reranker '{RERANKER_MODEL}'...")
        _reranker = CrossEncoder(RERANKER_MODEL)
    return _reranker

if TYPE_CHECKING:
    from .llm import LLMProvider


def hyde_expand(query: str, llm: "LLMProvider") -> str:
    """Generate a hypothetical document for the query to improve semantic search."""
    system = "You are a technical writer. Write a short document excerpt (3-5 sentences) that would directly answer the following question. Use technical vocabulary that would appear in real engineering documentation."
    messages = [{"role": "user", "content": query}]
    return llm.ask(system, messages)


@dataclass
class SearchResult:
    chunk_id: int
    doc_id: int
    title: str
    doc_type: str
    source: str
    path: str
    content: str
    score: float        # RRF score (higher = more relevant)
    metadata: dict[str, Any]


def search(
    conn,
    query: str,
    k: int = 5,
    doc_type: str | None = None,
    max_distance: float = 0.7,
    llm: "LLMProvider | None" = None,
    rerank: bool = True,
) -> list[SearchResult]:
    """
    Hybrid search over indexed chunks.

    query:    natural language question
    k:        number of results to return
    doc_type: optionally filter to 'runbook', 'incident', 'architecture', 'code'
    """
    # Embed the query into the same 384-dim space as the stored chunk embeddings.
    # Proximity in this space = semantic similarity.
    embed_text = hyde_expand(query, llm) if llm else query
    query_vector = embed_one(embed_text)

    type_filter = "AND d.doc_type = %(doc_type)s" if doc_type else ""

    sql = f"""
        WITH semantic AS (
            -- Rank chunks by cosine distance to query vector.
            -- <=> is the pgvector cosine distance operator (0 = identical, 2 = opposite).
            -- Lower distance = higher rank.
            SELECT
                c.id,
                ROW_NUMBER() OVER (ORDER BY c.embedding <=> %(embedding)s) AS rank
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL
            AND c.embedding <=> %(embedding)s < %(max_distance)s
            {type_filter}
            LIMIT 20
        ),
        keyword AS (
            -- Rank chunks by full-text relevance using postgres tsvector/tsquery.
            -- plainto_tsquery converts plain text to a tsquery (handles stop words, stemming).
            SELECT
                c.id,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank(to_tsvector('english', c.content),
                                     plainto_tsquery('english', %(query)s)) DESC
                ) AS rank
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE to_tsvector('english', c.content) @@ plainto_tsquery('english', %(query)s)
            {type_filter}
            LIMIT 20
        ),
        fused AS (
            -- Reciprocal Rank Fusion: combine both ranked lists into one score.
            -- FULL OUTER JOIN includes chunks that appeared in either list.
            SELECT
                COALESCE(s.id, k.id) AS id,
                COALESCE(1.0 / (60 + s.rank), 0) + COALESCE(1.0 / (60 + k.rank), 0) AS rrf_score
            FROM semantic s
            FULL OUTER JOIN keyword k ON s.id = k.id
        )
        SELECT
            c.id        AS chunk_id,
            d.id        AS doc_id,
            d.title,
            d.doc_type,
            d.source,
            d.path,
            d.metadata,
            c.content,
            f.rrf_score AS score
        FROM fused f
        JOIN chunks c    ON c.id = f.id
        JOIN documents d ON d.id = c.document_id
        ORDER BY f.rrf_score DESC
        LIMIT %(k)s
    """

    fetch_k = k * 4 if rerank else k
    params = {"embedding": query_vector, "query": query, "k": fetch_k, "doc_type": doc_type, "max_distance": max_distance}

    with dict_cursor(conn) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    results = [
        SearchResult(
            chunk_id=r["chunk_id"],
            doc_id=r["doc_id"],
            title=r["title"],
            doc_type=r["doc_type"],
            source=r["source"],
            path=r["path"],
            content=r["content"],
            score=float(r["score"]),
            metadata=r["metadata"] or {},
        )
        for r in rows
    ]

    if not rerank or not results:
        return results

    reranker = get_reranker()
    pairs = [[query, r.content] for r in results]
    scores = reranker.predict(pairs)
    for result, score in zip(results, scores):
        result.score = float(score)
    results.sort(key=lambda r: r.score, reverse=True)
    results = [r for r in results[:k] if r.score >= RERANKER_THRESHOLD]

    _apply_recency_boost(results)
    return results


def _apply_recency_boost(results: list[SearchResult], weight: float = 0.2) -> None:
    """Boost incident scores by recency based on INC number. Modifies results in place."""
    incidents = [r for r in results if r.doc_type == "incident" and "inc_number" in r.metadata]
    if len(incidents) < 2:
        return

    def inc_num(r: SearchResult) -> int:
        m = re.search(r"\d+", r.metadata["inc_number"])
        return int(m.group()) if m else 0

    nums = [inc_num(r) for r in incidents]
    lo, hi = min(nums), max(nums)
    if lo == hi:
        return

    for r in incidents:
        recency = (inc_num(r) - lo) / (hi - lo)  # 0 (oldest) to 1 (newest)
        r.score *= 1 + weight * recency
    results.sort(key=lambda r: r.score, reverse=True)
