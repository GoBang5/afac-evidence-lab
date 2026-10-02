"""Evaluate the production runner; inference inputs never include labels.

The v1 model_experiment remains a frozen single-pass baseline. This module calls
runner.run for every arm, then loads gold only after predictions are persisted.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import datetime
import hashlib
import json
import re
from pathlib import Path

from agent.io_utils import read_jsonl, write_json, write_jsonl
from agent.schema import AgentConfig
from .api_config import DEFAULT_CONFIG
from .budget import Budget
from .data import digest
from .experiments import finqa_inputs
from .model_experiment import answer_match
from .numeric import NumericConfig
from .runner import run as run_workflow

ARMS = {'workflow': NumericConfig(),
        'no_repair': NumericConfig(max_repair_rounds=0),
        'no_arithmetic_correction': NumericConfig(calculator=False)}


def structured_inputs(row):
    question, doc, candidates = finqa_inputs(row)
    # Replace lossy row sentences with raw cells. Do not guess that row zero is
    # a header. Its fact is packed separately, so all numbers remain attributable.
    first = row['table'][0] if row['table'] else []
    # A conservative header rule: each nonempty cell contains no amount other
    # than a four-digit year. Financial amounts in row zero keep it as data.
    amount_free = bool(first) and any(first) and all(not re.search(r'\d', re.sub(r'\b(?:19|20)\d{2}\b', '', str(cell))) for cell in first)
    header_hint = bool(first) and (not str(first[0]).strip() or
        re.search(r'\b(?:dollars|millions|thousands|billions|year|date)\b', str(first[0]), re.I) or
        all(re.fullmatch(r'(?:19|20)\d{2}', str(cell)) for cell in first) or
        all(not re.search(r'\d', str(cell)) for cell in first))
    header = amount_free and header_hint
    for candidate in candidates:
        if candidate['unit_type'] == 'table':
            i = int(candidate['locator']['fact_id'].split('_')[1])
            table_row = {'cells': row['table'][i]}
            if header and i != 0 and len(first) == len(row['table'][i]):
                table_row['column_labels'] = first
            candidate['text'] = json.dumps(table_row, ensure_ascii=False)
            candidate['locator']['quote_sha256'] = hashlib.sha256(candidate['text'].encode()).hexdigest()
    question['context_fact_ids'] = ['table_0'] if row['table'] else []
    if row['pre_text']:
        question['context_fact_ids'].append('text_' + str(len(row['pre_text']) - 1))
    return question, doc, candidates


def prepare(source, old_labels, out, per_type=4, exclude_heldout_labels=None):
    if out.exists() or per_type < 1:
        raise ValueError('Choose a new output and positive sample count')
    rows = json.loads(source.read_text())
    old = {r['qid'] for r in read_jsonl(old_labels)}
    excluded = {r['qid'] for r in read_jsonl(exclude_heldout_labels)} if exclude_heldout_labels else set()
    groups = {}
    for row in rows:
        kinds = {f.split('_')[0] for f in row['qa']['gold_inds']}
        kind = next(iter(kinds)) if len(kinds) == 1 else 'mixed'
        cohort = 'regression' if row['id'] in old else 'heldout'
        if cohort == 'heldout' and row['id'] in excluded:
            continue
        groups.setdefault((cohort, kind), []).append(row)
    out.mkdir(parents=True)
    manifest = {'version': 'workflow-v4', 'frozen_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'sampling': 'first SHA256(workflow-v2:qid), per evidence type; holdout excludes all 60 v1 questions',
                'scope': 'small exploratory regression/heldout pilot; no significance claim',
                'source_sha256': digest(source), 'old_labels_sha256': digest(old_labels),
                'excluded_heldout_ids': sorted(excluded),
                'budget': asdict(Budget()), 'arms': {k: asdict(v) for k, v in ARMS.items()},
                'metric': 'v1 direct numeric match, unchanged labels and five-decimal rounding; not official execution accuracy',
                'max_requests_total': per_type * 3 * 7,
                'identical_prompts': 'shared source/model/payload cache across arms; isolates arithmetic correction',
                'files_sha256': {}}
    for cohort in ('regression', 'heldout'):
        questions, docs, units, labels = [], [], [], []
        for kind in ('text', 'table', 'mixed'):
            pool = groups[(cohort, kind)]
            if len(pool) < per_type:
                raise ValueError('Not enough samples')
            selected = sorted(pool, key=lambda r: hashlib.sha256(('workflow-v2:' + r['id']).encode()).hexdigest())[:per_type]
            for row in selected:
                q, d, cs = structured_inputs(row)
                questions.append(q); docs.append(d); units.extend(cs)
                labels.append({'qid': row['id'], 'expected': row['qa']['exe_ans'],
                               'gold_facts': list(row['qa']['gold_inds']), 'stratum': kind,
                               'company': row['id'].split('/')[0]})
        folder = out / cohort
        folder.mkdir()
        for name, data in [('questions', questions), ('docs', docs), ('selector', units)]:
            write_jsonl(folder / (name + '.jsonl'), data)
        # Labels are a sibling file, never part of inference input or fingerprint.
        write_jsonl(out / (cohort + '-labels.jsonl'), labels)
    manifest['files_sha256'] = {str(p.relative_to(out)): digest(p) for p in out.rglob('*.jsonl')}
    write_json(out / 'protocol.json', manifest)
    return manifest


def run(prepared, out, api_config=DEFAULT_CONFIG):
    protocol = json.loads((prepared / 'protocol.json').read_text())
    for name, sha in protocol['files_sha256'].items():
        if digest(prepared / name) != sha:
            raise ValueError('Frozen input changed')
    if protocol['arms'] != {k: asdict(v) for k, v in ARMS.items()}:
        raise ValueError('Workflow arm configuration changed; prepare a new protocol')
    for cohort in ('regression', 'heldout'):
        for arm, numeric in ARMS.items():
            if cohort == 'heldout' and arm != 'workflow':
                continue
            summary = run_workflow(prepared / cohort, out / cohort / arm,
                                   budget=Budget(**protocol['budget']),
                                   config=AgentConfig(judge_mode='openai_compatible'),
                                   api_config=api_config, numeric=numeric,
                                   max_requests=protocol['max_requests_total'], request_cache=out / 'requests.sqlite')
            print(json.dumps({'cohort': cohort, 'arm': arm, **summary}), flush=True)
            if summary['failures']:
                raise RuntimeError('Workflow failed; preserve checkpoints and inspect before resuming')
    scores, metrics = [], []
    for cohort in ('regression', 'heldout'):
        labels = {r['qid']: r for r in read_jsonl(prepared / (cohort + '-labels.jsonl'))}
        for arm in ARMS:
            path = out / cohort / arm / 'questions.jsonl'
            if not path.exists():
                continue
            results = read_jsonl(path)
            for result in results:
                label = labels[result['qid']]
                facts = {e['fact_id'] for e in result['evidence']}
                scores.append({'qid': result['qid'], 'cohort': cohort, 'arm': arm, 'stratum': label['stratum'],
                               'predicted': result['answer'], 'expected': label['expected'],
                               'correct': int(answer_match(result['answer'], label['expected'])),
                               'abstained': result['answer'] is None, 'status': result['status'],
                               'all_gold_in_context': set(label['gold_facts']) <= facts,
                               'repair_rounds': result.get('repair_rounds', 0)})
            rows = [r for r in scores if r['cohort'] == cohort and r['arm'] == arm]
            summary = json.loads((path.parent / 'summary.json').read_text())
            metrics.append({'cohort': cohort, 'arm': arm, 'n': len(rows),
                            'correct': sum(r['correct'] for r in rows),
                            'abstained': sum(r['abstained'] for r in rows),
                            'all_gold_in_context': sum(r['all_gold_in_context'] for r in rows),
                            'repair_rounds': sum(r['repair_rounds'] for r in rows),
                            'logical_tokens': summary['total_tokens']})
    write_jsonl(out / 'scores.jsonl', scores)
    write_json(out / 'metrics.json', metrics)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--old-labels', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--per-type', type=int, default=4)
    p.add_argument('--exclude-heldout-labels', type=Path, help='Exclude a previously inspected pilot from the new holdout')
    p = sub.add_parser('run')
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--api-config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    result = prepare(args.source, args.old_labels, args.out, args.per_type, args.exclude_heldout_labels) if args.command == 'prepare' else run(args.prepared, args.out, args.api_config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
