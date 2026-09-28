"""Validate citation membership, verdict consistency and extractive provenance."""
from __future__ import annotations

import hashlib
from agent.verify import normalize_answer


def validate(question, rows, judge):
    problems = []
    ids = {r['evidence_id'] for r in rows}
    for row in rows:
        if hashlib.sha256(row['text'].encode()).hexdigest() != row['quote_sha256']:
            problems.append('quote_hash_mismatch')
    if len(ids) != len(rows):
        problems.append('duplicate_evidence_ids')
    answer, warnings = normalize_answer(judge.answer_raw, question.answer_format)
    if judge.mode == 'none':
        return '', 'needs_model_judge', sorted(set(problems))
    problems.extend(warnings)
    true_labels = []
    for label in question.options:
        judgement = judge.option_judgement.get(label, {})
        verdict = judgement.get('verdict')
        refs = judgement.get('evidence_ids', [])
        if not isinstance(refs, list) or any(type(ref) is not int or ref not in ids for ref in refs):
            problems.append(f'invalid_citation:{label}')
            refs = []
        if verdict not in ('TRUE', 'FALSE', 'UNKNOWN'):
            problems.append(f'invalid_verdict:{label}')
        if verdict in ('TRUE', 'FALSE') and not refs:
            problems.append(f'uncited_verdict:{label}')
        if verdict == 'UNKNOWN':
            problems.append(f'insufficient_evidence:{label}')
        if verdict == 'TRUE':
            true_labels.append(label)
    if ''.join(sorted(true_labels)) != answer:
        problems.append('answer_verdict_mismatch')
    if not answer:
        problems.append('empty_answer')
    if judge.status != 'model_judged':
        problems.append(f'judge_status:{judge.status}')
    return answer, 'needs_review' if problems else 'validated_structure', sorted(set(problems))
