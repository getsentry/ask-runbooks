"""
Local filesystem source.

Walks one or more directories and returns all .md files as Documents.

config.yaml example:
    sources:
      local:
        - path: ./docs/runbooks
          doc_type: runbook
        - path: ./docs/incidents
          doc_type: incident
        - path: ./docs/architecture
          doc_type: architecture
"""

from __future__ import annotations

from pathlib import Path

from .base import Document, Source
from ..ingest import extract_title


class LocalSource(Source):
    def __init__(self, directories: list[dict], config_dir: str = "") -> None:
        self.directories = directories
        self.base = Path(config_dir) if config_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "local"

    def sync(self) -> list[Document]:
        docs = []
        for entry in self.directories:
            dir_path = (self.base / entry["path"]).expanduser().resolve()
            doc_type = entry["doc_type"]

            if not dir_path.exists():
                print(f"  [local] Warning: path does not exist: {dir_path}")
                continue

            for md_path in sorted(dir_path.rglob("*.md")):
                content = md_path.read_text(encoding="utf-8")
                title = extract_title(content, fallback=md_path.stem)
                docs.append(Document(
                    source="local",
                    doc_type=doc_type,
                    path=str(md_path),
                    title=title,
                    content=content,
                    metadata={"filename": md_path.name},
                ))

        print(f"  [local] Found {len(docs)} documents")
        return docs
