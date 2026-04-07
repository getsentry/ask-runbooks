"""
GitHub source.

Fetches markdown files from one or more repos/paths via the GitHub REST API.
Set GITHUB_TOKEN in .env for private repos and higher rate limits.

config.yaml example:
    sources:
      github:
        - repo: myorg/myrepo
          paths:
            - docs/runbooks
            - docs/architecture
          doc_type: runbook
"""

from __future__ import annotations

import base64
import os
import urllib.request
import urllib.error
import json

from .base import Document, Source
from ..ingest import extract_title


class GitHubSource(Source):
    API = "https://api.github.com"

    def __init__(self, repos: list[dict]):  # type: ignore[type-arg]
        """
        repos: list of {"repo": str, "paths": list[str], "doc_type": str, "branch": str}
        """
        self.repos = repos
        self.token = os.environ.get("GITHUB_TOKEN")

    @property
    def name(self) -> str:
        return "github"

    def _get(self, url: str) -> dict | list:  # type: ignore[type-arg]
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())  # type: ignore[no-any-return]

    def _list_files(self, repo: str, path: str, branch: str) -> list[dict]:  # type: ignore[type-arg]
        """Recursively list all .md files under path."""
        url = f"{self.API}/repos/{repo}/contents/{path}?ref={branch}"
        try:
            items = self._get(url)
        except urllib.error.HTTPError as e:
            print(f"  [github] Warning: {repo}/{path} returned {e.code}")
            return []
        if isinstance(items, dict):
            return [items] if items.get("name", "").endswith(".md") else []
        files = []
        for item in items:
            if item["type"] == "file" and item["name"].endswith(".md"):
                files.append(item)
            elif item["type"] == "dir":
                files.extend(self._list_files(repo, item["path"], branch))
        return files

    def sync(self) -> list[Document]:
        docs = []
        for entry in self.repos:
            repo = entry["repo"]
            paths = entry.get("paths", [""])
            doc_type = entry.get("doc_type", "architecture")
            repo_meta = self._get(f"{self.API}/repos/{repo}")
            branch = repo_meta["default_branch"]

            for path in paths:
                for file_meta in self._list_files(repo, path, branch):
                    file_data = self._get(file_meta["url"])
                    content = base64.b64decode(file_data["content"]).decode("utf-8")  # type: ignore[index]
                    file_path = file_data["path"]  # type: ignore[index]
                    title = extract_title(content, fallback=file_meta["name"].removesuffix(".md"))
                    docs.append(Document(
                        source="github",
                        doc_type=doc_type,
                        path=f"{repo}/{file_path}",
                        title=title,
                        content=content,
                        metadata={"repo": repo, "html_url": file_meta.get("html_url", "")},
                    ))

        print(f"  [github] Found {len(docs)} documents")
        return docs
