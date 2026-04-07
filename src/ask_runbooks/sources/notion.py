"""
Notion source.

Recursively fetches pages from configured root pages or databases,
converts block content to markdown, and returns as Documents.

Follows child_page blocks only — link_to_page (links to other pages) are skipped.
child_database blocks within pages are also skipped.

config.yaml example:
    sources:
      notion:
        - page_id: abc123        # root page — walks all nested child pages
          doc_type: incident
        - page_id: def456        # another root, different doc type
          doc_type: architecture
        - database_id: ghi789    # Notion database — fetches all rows as pages
          doc_type: runbook
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Optional

from .base import Document, Source

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionSource(Source):
    def __init__(self, entries: list[dict]):
        """
        entries: list of {"page_id": str, "doc_type": str}
                       or {"database_id": str, "doc_type": str}
        """
        self.entries = entries
        self.token = os.environ.get("NOTION_TOKEN")
        if not self.token:
            raise ValueError("NOTION_TOKEN not set in environment")

    @property
    def name(self) -> str:
        return "notion"

    def _get(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        url = f"{NOTION_API}/{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Notion-Version", NOTION_VERSION)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def _get_blocks(self, block_id: str) -> list[dict]:
        """Fetch all blocks for a page/block, handling pagination."""
        blocks = []
        cursor = None
        while True:
            path = f"blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._get(path)
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return blocks

    def _rich_text(self, rich_text: list[dict]) -> str:
        """Extract plain text from a Notion rich_text array."""
        return "".join(t.get("plain_text", "") for t in rich_text)

    def _blocks_to_markdown(self, blocks: list[dict], depth: int = 0) -> str:
        """Convert a list of Notion blocks to markdown text."""
        lines = []
        indent = "  " * depth

        for block in blocks:
            btype = block.get("type")
            content = block.get(btype, {})

            if btype == "paragraph":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"{indent}{text}" if text else "")

            elif btype == "heading_1":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"# {text}")

            elif btype == "heading_2":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"## {text}")

            elif btype == "heading_3":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"### {text}")

            elif btype == "bulleted_list_item":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"{indent}- {text}")

            elif btype == "numbered_list_item":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"{indent}1. {text}")

            elif btype == "code":
                text = self._rich_text(content.get("rich_text", []))
                lang = content.get("language", "")
                lines.append(f"```{lang}\n{text}\n```")

            elif btype == "quote":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"> {text}")

            elif btype == "callout":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"> {text}")

            elif btype == "divider":
                lines.append("---")

            elif btype == "toggle":
                text = self._rich_text(content.get("rich_text", []))
                lines.append(f"{indent}{text}")

            elif btype in ("child_page", "link_to_page", "child_database"):
                # child_page is handled by _walk_page recursion, not here
                # link_to_page and child_database are skipped
                pass

            # Fetch nested children for blocks that can have them
            if block.get("has_children") and btype not in ("child_page", "child_database"):
                children = self._get_blocks(block["id"])
                lines.append(self._blocks_to_markdown(children, depth + 1))

        return "\n".join(lines)

    def _page_title(self, page: dict) -> str:
        """Extract the title from a page object."""
        props = page.get("properties", {})
        # Title property can be named "title", "Name", or "Title"
        for key in ("title", "Name", "Title"):
            prop = props.get(key, {})
            rich_text = prop.get("title", [])
            if rich_text:
                return self._rich_text(rich_text)
        return page.get("id", "Untitled")

    def _walk_page(self, page_id: str, doc_type: str, visited: set[str]) -> list[Document]:
        """
        Recursively fetch a page and all its child_page descendants.
        Skips link_to_page — only follows pages that physically live under this one.
        """
        if page_id in visited:
            return []
        visited.add(page_id)

        try:
            page = self._get(f"pages/{page_id}")
        except urllib.error.HTTPError as e:
            print(f"  [notion] Warning: could not fetch page {page_id}: {e.code}")
            return []

        title = self._page_title(page)
        blocks = self._get_blocks(page_id)
        content = f"# {title}\n\n{self._blocks_to_markdown(blocks)}"

        docs = [Document(
            source="notion",
            doc_type=doc_type,
            path=f"notion/{page_id}",
            title=title,
            content=content,
            metadata={"notion_id": page_id, "url": page.get("url", "")},
        )]

        # Recurse into child pages only
        for block in blocks:
            if block.get("type") == "child_page":
                docs.extend(self._walk_page(block["id"], doc_type, visited))

        return docs

    def _walk_database(self, database_id: str, doc_type: str) -> list[Document]:
        """Fetch all pages in a Notion database."""
        docs = []
        cursor = None
        visited: set[str] = set()

        while True:
            body: dict = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            data = self._get(f"databases/{database_id}/query", method="POST", body=body)

            for page in data.get("results", []):
                docs.extend(self._walk_page(page["id"], doc_type, visited))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return docs

    def sync(self) -> list[Document]:
        docs = []
        visited: set[str] = set()

        for entry in self.entries:
            doc_type = entry.get("doc_type", "architecture")

            if "page_id" in entry:
                page_docs = self._walk_page(entry["page_id"], doc_type, visited)
                docs.extend(page_docs)
                print(f"  [notion] page {entry['page_id']}: {len(page_docs)} pages")

            elif "database_id" in entry:
                db_docs = self._walk_database(entry["database_id"], doc_type)
                docs.extend(db_docs)
                print(f"  [notion] database {entry['database_id']}: {len(db_docs)} pages")

        print(f"  [notion] Total: {len(docs)} documents")
        return docs
