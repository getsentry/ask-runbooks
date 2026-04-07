"""
ask-runbooks — query runbooks, incidents, architecture docs, and code.

Usage:
    ask-runbooks
"""

import os


def dedup_by_doc(results):
    """One result per document (highest score wins), preserving rank order."""
    seen = {}
    for r in results:
        if r.doc_id not in seen or r.score > seen[r.doc_id].score:
            seen[r.doc_id] = r
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)


def print_sources(results):
    print("\n--- Sources ---")
    for i, r in enumerate(results, 1):
        print(f"[{i}] ({r.doc_type}) {r.title}")
        print(f"     {r.path}")


def main():
    from .db import get_conn
    from .llm import build_provider
    from .search import search, SearchResult
    from .prompt import answer_in_session
    from .sync import load_config

    config = load_config()
    conn = get_conn()
    llm = build_provider(config)
    context_note = config.get("context", "")

    print("Session started. Type 'quit' to exit.\n")

    history = []
    accumulated: dict[int, SearchResult] = {}  # chunk_id -> SearchResult

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            break

        new_results = search(conn, question, llm=llm)
        for r in new_results:
            if r.chunk_id not in accumulated:
                accumulated[r.chunk_id] = r

        all_results = dedup_by_doc(list(accumulated.values()))
        if not all_results:
            print("No relevant documents found.\n")
            continue

        response = answer_in_session(question, all_results, history, llm, context_note)
        print(f"\n{response}\n")

        print_sources(all_results)
        print()

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": response})

    conn.close()


if __name__ == "__main__":
    main()
