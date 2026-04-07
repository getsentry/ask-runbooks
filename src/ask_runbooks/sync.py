"""
sync — download docs from configured sources and index them.

Usage:
    sync                        # sync all sources
    sync --source local         # sync one source
    sync --dry-run              # show what would be synced, no writes
    sync --verbose              # show per-doc progress

Run on a schedule with cron, e.g.:
    0 * * * * cd /path/to/ask-runbooks && sync   # hourly
"""

import argparse
import os
import sys

# Default config — edit or replace with config.yaml loading later
DEFAULT_CONFIG = {
    "sources": {
        "local": [
            # {"path": "./docs/runbooks",    "doc_type": "runbook"},
            # {"path": "./docs/incidents",   "doc_type": "incident"},
            # {"path": "./docs/architecture","doc_type": "architecture"},
        ],
        "github": [
            # {
            #   "repo": "myorg/myrepo",
            #   "paths": ["docs/runbooks"],
            #   "doc_type": "runbook",
            #   "branch": "main",
            # },
        ],
    }
}


def load_config() -> dict:
    import yaml
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["_dir"] = os.path.dirname(config_path)
        return config
    return DEFAULT_CONFIG


def build_sources(config: dict) -> list:
    from .sources.local import LocalSource
    from .sources.github import GitHubSource

    sources_config = config.get("sources", {})
    sources = []

    if sources_config.get("local"):
        sources.append(LocalSource(sources_config["local"], config.get("_dir", "")))

    if sources_config.get("github"):
        sources.append(GitHubSource(sources_config["github"]))

    if sources_config.get("notion"):
        from .sources.notion import NotionSource
        sources.append(NotionSource(sources_config["notion"]))

    if sources_config.get("notion_zip"):
        from .sources.notion_zip import NotionZipSource
        sources.append(NotionZipSource(sources_config["notion_zip"], config.get("_dir", "")))

    return sources


def main():
    parser = argparse.ArgumentParser(description="Sync docs from all configured sources")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch docs but don't write to DB")
    args = parser.parse_args()

    try:
        config = load_config()
    except ImportError:
        print("Note: pyyaml not installed, using default config")
        config = DEFAULT_CONFIG

    sources = build_sources(config)
    if not sources:
        print("No sources configured. Edit config.yaml to add sources.")
        sys.exit(1)

    all_docs = []
    for source in sources:
        print(f"Syncing {source.name}...")
        docs = source.sync()
        all_docs.extend(docs)

    print(f"\nTotal: {len(all_docs)} documents fetched")

    if args.dry_run:
        print("Dry run — not writing to DB")
        for doc in all_docs:
            print(f"  [{doc.doc_type}] {doc.title}  ({doc.source}: {doc.path})")
        return

    from .db import get_conn, migrate
    from .ingest import ingest_documents

    migrate()
    conn = get_conn()

    print("Indexing...")
    stats = ingest_documents(conn, all_docs)
    conn.close()

    print(
        f"Done. inserted={stats['inserted']} updated={stats['updated']} "
        f"skipped={stats['skipped']} chunks={stats['chunks']}"
    )


if __name__ == "__main__":
    main()
