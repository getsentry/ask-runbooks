from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any


@dataclass
class Document:
    source: str       # 'local', 'github', 'notion'
    doc_type: str     # 'runbook', 'incident', 'architecture', 'code'
    path: str         # unique identifier within source (filepath or URL)
    title: str
    content: str      # full markdown text
    metadata: dict[str, Any] = field(default_factory=dict)


class Source(ABC):
    """
    A Source knows how to fetch documents from one external system.
    sync() returns all current documents — the indexer handles diffing against what's stored.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def sync(self) -> list[Document]: ...
