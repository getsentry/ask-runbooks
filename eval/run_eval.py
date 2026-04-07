"""
Eval runner — score search results against expected incidents and runbooks.

Usage:
    uv run python eval/run_eval.py
    uv run python eval/run_eval.py --cases eval/cases.yaml --case 0
"""

import os
import sys

import yaml
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def title_match(result_title: str, expected_title: str) -> bool:
    return expected_title.lower() in result_title.lower()


def inc_match(result, inc_number: str) -> bool:
    # Match by metadata inc_number or title containing the INC number
    meta_inc = (result.metadata or {}).get("inc_number", "")
    return meta_inc == inc_number or inc_number.lower() in result.title.lower()


def evaluate_case(case: dict, results) -> dict:
    expected_incidents = case.get("expected_incidents", [])
    expected_runbooks = case.get("expected_runbooks", [])

    result_titles = {r.title for r in results}

    incident_hits = [
        inc for inc in expected_incidents
        if any(inc_match(r, inc) for r in results if r.doc_type == "incident")
    ]
    runbook_hits = [
        rb for rb in expected_runbooks
        if any(title_match(r.title, rb) for r in results if r.doc_type == "runbook")
    ]

    return {
        "incident_recall": len(incident_hits) / len(expected_incidents) if expected_incidents else None,
        "runbook_recall": len(runbook_hits) / len(expected_runbooks) if expected_runbooks else None,
        "incident_hits": incident_hits,
        "incident_misses": [i for i in expected_incidents if i not in incident_hits],
        "runbook_hits": runbook_hits,
        "runbook_misses": [r for r in expected_runbooks if r not in runbook_hits],
        "returned": [f"({r.doc_type}) {r.title}" for r in results],
    }


def main():
    cases_path = os.path.join(os.path.dirname(__file__), "cases.yaml")
    with open(cases_path) as f:
        cases = yaml.safe_load(f)

    from ask_runbooks.db import get_conn
    from ask_runbooks.llm import build_provider
    from ask_runbooks.search import search
    from ask_runbooks.ask import dedup_by_doc
    from ask_runbooks.sync import load_config

    config = load_config()
    conn = get_conn(autocommit=True)
    llm = build_provider(config)

    total_incident_recall = []
    total_runbook_recall = []

    for i, case in enumerate(cases):
        idx = i
        query = case["query"]
        print(f"\n[{idx}] {query}")

        incidents = dedup_by_doc(search(conn, query, doc_type="incident", llm=llm))
        runbooks = dedup_by_doc(search(conn, query, doc_type="runbook", llm=llm))
        results = incidents + runbooks
        score = evaluate_case(case, results)

        if score["incident_recall"] is not None:
            total_incident_recall.append(score["incident_recall"])
            print(f"  incidents  {score['incident_recall']:.0%}  hits={score['incident_hits']}  misses={score['incident_misses']}")
        if score["runbook_recall"] is not None:
            total_runbook_recall.append(score["runbook_recall"])
            print(f"  runbooks   {score['runbook_recall']:.0%}  hits={score['runbook_hits']}  misses={score['runbook_misses']}")

        print(f"  returned: {score['returned']}")

    if len(cases) > 1:
        print("\n--- Summary ---")
        if total_incident_recall:
            print(f"  incident recall: {sum(total_incident_recall)/len(total_incident_recall):.0%}  ({len(total_incident_recall)} cases)")
        if total_runbook_recall:
            print(f"  runbook recall:  {sum(total_runbook_recall)/len(total_runbook_recall):.0%}  ({len(total_runbook_recall)} cases)")

    conn.close()


if __name__ == "__main__":
    main()
