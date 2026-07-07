"""Evidence packing utilities."""

from __future__ import annotations

from typing import Any

from .schema import AgentConfig, ScoredEvidence


def pack_evidence(
    option_evidence: dict[str, list[ScoredEvidence]],
    question_evidence: list[ScoredEvidence],
    config: AgentConfig,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    option_rows = {
        label: [item.to_row(config.max_quote_chars) for item in rows]
        for label, rows in sorted(option_evidence.items())
    }

    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def add(item: ScoredEvidence, label: str | None) -> None:
        cid = item.candidate.candidate_id
        if cid not in by_id:
            row = item.to_row(config.max_quote_chars)
            row["support_options"] = []
            row["retrieval_options"] = []
            by_id[cid] = row
            order.append(cid)
        if label and label not in by_id[cid]["support_options"]:
            by_id[cid]["support_options"].append(label)
        if item.option and item.option not in by_id[cid]["retrieval_options"]:
            by_id[cid]["retrieval_options"].append(item.option)

    for label, rows in sorted(option_evidence.items()):
        for item in rows[: config.min_evidence_per_option]:
            add(item, label)

    all_items: list[ScoredEvidence] = []
    for rows in option_evidence.values():
        all_items.extend(rows)
    all_items.extend(question_evidence)
    all_items.sort(key=lambda item: item.score, reverse=True)
    for item in all_items:
        if len(order) >= config.final_evidence_max:
            break
        add(item, item.option)

    packed: list[dict[str, Any]] = []
    for evidence_id, cid in enumerate(order[: config.final_evidence_max], 1):
        row = by_id[cid]
        row["evidence_id"] = evidence_id
        packed.append(row)
    return option_rows, packed

