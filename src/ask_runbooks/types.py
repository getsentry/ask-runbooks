from __future__ import annotations

from typing import TypedDict


class Message(TypedDict):
    role: str
    content: str


class Session(TypedDict):
    history: list[Message]
    last_active: float


class AskRequest(TypedDict):
    question: str
