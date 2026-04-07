"""
Notion ZIP export source.

Reads markdown files from a Notion export zip, extracting page IDs from
filenames to construct notion.so links.

Notion export filenames end with a 32-char hex page ID, e.g.:
    [INC-123] Some Incident Title abc123def456789012345678abcdef01.md

config.yaml example:
    sources:
      notion_zip:
        - path: ./.data/incidents
          doc_type: incident
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .base import Document, Source
from ..ingest import extract_title, extract_incident_fields

# Notion page IDs are 32 hex chars at the end of the filename stem
_NOTION_ID_RE = re.compile(r"([0-9a-f]{32})$")


def _parse_filename(name: str) -> tuple[str, str | None]:
    """Return (clean title, notion_url or None) from a Notion export filename."""
    stem = Path(name).stem
    m = _NOTION_ID_RE.search(stem)
    if m:
        page_id = m.group(1)
        title = stem[: m.start()].rstrip()
        url = f"https://notion.so/{page_id}"
        return title, url
    return stem, None


class NotionZipSource(Source):
    def __init__(self, entries: list[dict], config_dir: str = "") -> None:
        self.entries = entries
        self.base = Path(config_dir) if config_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "notion_zip"

    def _read_zip(self, zip_path: Path, doc_type: str, max_depth: int | None = None) -> list[Document]:
        import io
        with zipfile.ZipFile(zip_path) as zf:
            docs = self._read_zip_obj(zf, zip_path, doc_type, max_depth)
            for name in zf.namelist():
                if name.endswith(".zip"):
                    inner_zip = zipfile.ZipFile(io.BytesIO(zf.read(name)))
                    docs.extend(self._read_zip_obj(inner_zip, zip_path / name, doc_type, max_depth))
        return docs

    def _read_zip_obj(self, zf: zipfile.ZipFile, zip_path: Path, doc_type: str, max_depth: int | None = None) -> list[Document]:
        docs = []
        for name in sorted(zf.namelist()):
            if not name.endswith(".md"):
                continue
            if max_depth is not None and len(Path(name).parts) > max_depth:
                continue
            content = zf.read(name).decode("utf-8")
            fallback_title, url = _parse_filename(name)
            title = extract_title(content, fallback=fallback_title)
            metadata: dict = {"zip": zip_path.name}
            if url:
                metadata["url"] = url
            if doc_type == "incident":
                metadata.update(extract_incident_fields(content))
            docs.append(Document(
                source="notion_zip",
                doc_type=doc_type,
                path=f"{zip_path}/{name}",
                title=title,
                content=content,
                metadata=metadata,
            ))
        return docs

    def sync(self) -> list[Document]:
        docs = []
        for entry in self.entries:
            dir_path = (self.base / entry["path"]).expanduser().resolve()
            doc_type = entry["doc_type"]

            if not dir_path.exists():
                print(f"  [notion_zip] Warning: path does not exist: {dir_path}")
                continue

            max_depth = entry.get("max_depth")
            for zip_path in sorted(dir_path.glob("*.zip")):
                docs.extend(self._read_zip(zip_path, doc_type, max_depth))

        print(f"  [notion_zip] Found {len(docs)} documents")
        return docs
