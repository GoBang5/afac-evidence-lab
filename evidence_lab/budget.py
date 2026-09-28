"""Pack whole evidence units under the actual judge-message character budget.

Coverage here means retrieval provenance, never truth or semantic sufficiency.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from agent.prompting import build_judge_messages


@dataclass(frozen=True)
class Budget:
    max_prompt_chars: int = 12000
    max_evidence: int = 18
    max_quote_chars: int = 900

    def __post_init__(self):
        if min(self.max_prompt_chars, self.max_evidence, self.max_quote_chars) <= 0:
            raise ValueError('All evidence limits must be positive')


def prompt_chars(question, rows):
    return sum(len(m['content']) for m in build_judge_messages(question, rows))


def pack(question, options, stem, budget=Budget()):
    fixed = prompt_chars(question, [])
    if fixed > budget.max_prompt_chars:
        raise ValueError('Question and prompt overhead alone exceed character budget')
    # Aggregate all provenance before selection. An option label is a retrieval
    # route, not a TRUE judgement. Avoid the upstream "support_options" inference.
    by_id, routes = {}, {}
    for label, items in [*sorted(options.items()), (None, stem)]:
        for item in items:
            cid = item.candidate.candidate_id
            if cid not in by_id or item.score > by_id[cid].score:
                by_id[cid] = item
            if label:
                routes.setdefault(cid, set()).add(label)
    pool = []
    for cid, item in by_id.items():
        row = item.to_row(budget.max_quote_chars)
        row['support_options'] = []
        row['retrieval_options'] = sorted(routes.get(cid, set()))
        row['quote_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
        row['quote_truncated'] = len(item.candidate.text.strip()) > len(row['text'])
        row['locator'] = dict(row['locator'])
        pool.append(row)
    # Satisfy uncovered docs/options first, then relevance per incremental cost.
    # A deterministic greedy set cover heuristic, not an optimal solver.
    selected, covered = [], set()
    goals = {('option', label) for label in question.options}
    goals |= {('doc', did) for did in question.doc_ids}
    while pool and len(selected) < budget.max_evidence:
        choices = []
        for row in pool:
            candidate = {**row, 'evidence_id': len(selected) + 1}
            cost = prompt_chars(question, selected + [candidate])
            if cost > budget.max_prompt_chars:
                continue
            coverage = {('doc', row['doc_id'])} | {('option', label) for label in row['retrieval_options']}
            gain = len((coverage & goals) - covered)
            marginal = max(1, cost - prompt_chars(question, selected))
            choices.append((gain, row['score'] / marginal, row['candidate_id'], candidate, coverage))
        if not choices:
            break
        _, _, _, chosen, coverage = max(choices, key=lambda x: (x[0], x[1], x[2]))
        selected.append(chosen)
        covered |= coverage
        pool = [r for r in pool if r['candidate_id'] != chosen['candidate_id']]
    return selected, {
        'prompt_chars': prompt_chars(question, selected), 'max_prompt_chars': budget.max_prompt_chars,
        'fixed_prompt_chars': fixed, 'missing_documents': sorted(v for k, v in goals - covered if k == 'doc'),
        'missing_option_routes': sorted(v for k, v in goals - covered if k == 'option'),
        'scope': 'characters in system+user message contents; not model tokens or answer accuracy',
    }
