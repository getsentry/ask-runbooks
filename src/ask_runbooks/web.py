"""
ask-runbooks web UI — minimal FastAPI chat interface.

Usage:
    ask-runbooks-web
"""

from __future__ import annotations

import importlib.resources
import time
import uuid
from .types import AskRequest, Message, Session


HISTORY_MAX_TURNS = 10   # keep last N user/assistant pairs
SESSION_TTL = 60 * 30    # drop sessions idle for 30 min

HTML = importlib.resources.files("ask_runbooks").joinpath("index.html").read_text()



def main() -> None:
    import uvicorn
    from fastapi import Cookie, FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    from .ask import dedup_by_doc
    from .db import get_conn
    from .embeddings import get_model
    from .llm import build_provider
    from .prompt import answer_in_session
    from .search import search, get_reranker
    from .sync import load_config

    config = load_config()
    conn = get_conn(autocommit=True)  # read-only — don't hold open transactions
    llm = build_provider(config)
    context_note = config.get("context", "")
    get_model()     # load embedding model at startup
    get_reranker()  # load reranker at startup

    sessions: dict[str, Session] = {}

    def get_session(session_id: str | None) -> tuple[str, Session]:
        now = time.time()
        # evict expired sessions
        expired = [k for k, v in sessions.items() if now - v["last_active"] > SESSION_TTL]
        for k in expired:
            del sessions[k]

        if session_id and session_id in sessions:
            return session_id, sessions[session_id]

        sid = str(uuid.uuid4())
        sessions[sid] = {"history": [], "last_active": now}
        return sid, sessions[sid]

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return HTML

    @app.post("/ask")
    def ask(req: AskRequest, session_id: str | None = Cookie(default=None)) -> JSONResponse:
        sid, session = get_session(session_id)
        question = req["question"]
        history = session["history"]

        incidents = dedup_by_doc(search(conn, question, doc_type="incident", llm=llm))
        runbooks = dedup_by_doc(search(conn, question, doc_type="runbook", llm=llm))
        t0 = time.time()
        answer = answer_in_session(question, incidents + runbooks, history, llm, context_note)
        llm_ms = int((time.time() - t0) * 1000)
        sources = [
            {"title": r.title, "url": r.metadata.get("html_url") or r.metadata.get("url") or r.path, "doc_type": r.doc_type}
            for r in incidents + runbooks
        ]

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        # trim to last N turns (each turn = 2 messages)
        if len(history) > HISTORY_MAX_TURNS * 2:
            session["history"] = history[-(HISTORY_MAX_TURNS * 2):]
        session["last_active"] = time.time()

        response = JSONResponse({"answer": answer, "sources": sources, "llm_ms": llm_ms})
        response.set_cookie("session_id", sid)
        return response

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
