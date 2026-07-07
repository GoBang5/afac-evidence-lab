#!/usr/bin/env python3
"""Evaluate blind document routing by hiding Group A `doc_ids`.

This is a proxy for B-list document selection.  It does not use answers or
models.  For each Group A question, the evaluator removes `doc_ids`, runs the
agent doc router, and reports whether the routed top-k contains any/all gold
documents.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.io_utils import read_jsonl, write_json, write_jsonl
from agent.retrieval import CandidateIndex
from agent.schema import Question


def parse_top_ks(raw: str) -> list[int]:
    out: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value <= 0:
            raise ValueError("top-k values must be positive")
        out.append(value)
    return sorted(set(out))


def evaluate(
    questions: list[dict[str, Any]],
    index: CandidateIndex,
    top_ks: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    max_k = max(top_ks)
    stats = {
        k: {
            "total": 0,
            "any_hit": 0,
            "all_hit": 0,
            "by_domain": defaultdict(lambda: {"total": 0, "any_hit": 0, "all_hit": 0}),
        }
        for k in top_ks
    }
    failures: list[dict[str, Any]] = []

    for row in questions:
        gold = [str(doc_id) for doc_id in row.get("doc_ids") or []]
        if not gold:
            continue
        question = Question.from_row({**row, "doc_ids": []})
        routed, _ = index.route_docs(question, top_k=max_k)
        gold_set = set(gold)
        for k in top_ks:
            pred = routed[:k]
            pred_set = set(pred)
            any_hit = bool(gold_set & pred_set)
            all_hit = gold_set <= pred_set
            stat = stats[k]
            stat["total"] += 1
            stat["any_hit"] += int(any_hit)
            stat["all_hit"] += int(all_hit)
            domain_stat = stat["by_domain"][question.domain]
            domain_stat["total"] += 1
            domain_stat["any_hit"] += int(any_hit)
            domain_stat["all_hit"] += int(all_hit)
            if k == max_k and not all_hit:
                failures.append(
                    {
                        "qid": question.qid,
                        "domain": question.domain,
                        "answer_format": question.answer_format,
                        "question": question.question,
                        "gold_doc_ids": gold,
                        "routed_doc_ids": pred,
                        "missing_gold_doc_ids": sorted(gold_set - pred_set),
                        "any_hit": any_hit,
                        "all_hit": all_hit,
                    }
                )

    summary_by_k: dict[str, Any] = {}
    for k in top_ks:
        stat = stats[k]
        total = max(1, stat["total"])
        by_domain = {}
        for domain, values in sorted(stat["by_domain"].items()):
            d_total = max(1, values["total"])
            by_domain[domain] = {
                "total": values["total"],
                "any_hit": values["any_hit"],
                "all_hit": values["all_hit"],
                "any_recall": values["any_hit"] / d_total,
                "all_recall": values["all_hit"] / d_total,
            }
        summary_by_k[str(k)] = {
            "total": stat["total"],
            "any_hit": stat["any_hit"],
            "all_hit": stat["all_hit"],
            "any_recall": stat["any_hit"] / total,
            "all_recall": stat["all_hit"] / total,
            "by_domain": by_domain,
        }

    failure_domains = Counter(row["domain"] for row in failures)
    summary = {
        "top_ks": top_ks,
        "candidate_docs": len(index.docs()),
        "candidate_units": index.candidate_count(),
        "summary_by_k": summary_by_k,
        "max_k_failures": len(failures),
        "max_k_failure_domains": dict(sorted(failure_domains.items())),
    }
    return summary, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", default="processed_data/agent_evidence_seed/group_a_all_questions.jsonl")
    parser.add_argument("--selector", default="processed_data/selector/group_a_selector_search.jsonl")
    parser.add_argument("--docs", default="processed_data/docs.jsonl")
    parser.add_argument("--top-ks", default="1,3,5,8,10")
    parser.add_argument("--output-dir", default="runs/doc_routing_eval")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    top_ks = parse_top_ks(args.top_ks)
    questions = read_jsonl(args.questions)
    index = CandidateIndex.from_paths(args.selector, args.docs)
    summary, failures = evaluate(questions, index, top_ks)
    out_dir = Path(args.output_dir)
    write_json(out_dir / "doc_routing_summary.json", summary)
    write_jsonl(out_dir / "doc_routing_failures.jsonl", failures)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

