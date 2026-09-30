"""Offline generalization and controlled ablations. No model calls or gold input.

FinQA measures retrieval inside the provided example context, not long-document
search, numerical reasoning accuracy, or a FinQA leaderboard submission.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import statistics
import time

from agent.io_utils import read_jsonl, write_json, write_jsonl
from agent.retrieval import CandidateIndex
from agent.schema import Question
from .benchmark import baseline, signature
from .budget import Budget, pack
from .data import digest
from .retrieval import CachedIndex, retrieve

FINQA_COMMIT = '0f16e2867befa6840783e58be38c9efb9229d742'
FINQA_VARIANTS = ('full', 'no_numeric_bonus', 'token_only')
AFAC_VARIANTS = ('full', 'no_doc_priority', 'no_option_priority',
                 'no_coverage_priority', 'no_option_queries', 'no_cost_normalization')


def table_row_text(header, row):
    """Match FinQA's corrected, label-independent table template.

    Specification: czyssrs/FinQA code/utils/general_utils.py (MIT), pinned above.
    Identical formatting is applied to every row, including the header row,
    following its test-mode retriever. No gold evidence strings are read here.
    """
    prefix = header[0] + ' ' if header[0] else ''
    text = prefix + ''.join('the ' + row[0] + ' of ' + head + ' is ' + cell + ' ; '
                           for head, cell in zip(header[1:], row[1:]))
    return ' '.join(part for part in text.split(' ') if part).strip()


def finqa_inputs(row):
    """Whitelist model/retrieval inputs; never copy the raw qa dictionary."""
    qid = row['id']
    question = {'qid': qid, 'question': row['qa']['question'], 'domain': 'financial_reports',
                'split': 'finqa_public_test', 'options': {}, 'answer_format': 'numeric',
                'doc_ids': [qid]}
    texts = [(f'text_{i}', text, 'text')
             for i, text in enumerate(row['pre_text'] + row['post_text'])]
    table = row['table']
    texts += [(f'table_{i}', table_row_text(table[0], cells), 'table')
              for i, cells in enumerate(table)] if table else []
    candidates = []
    for order, (fact, text, kind) in enumerate(texts):
        candidates.append({'candidate_id': qid + '::' + fact, 'doc_id': qid,
                           'text': text, 'unit_type': kind, 'modality': kind,
                           'quality_tier': 'dataset', 'evidence_weight': 1.0,
                           'reading_order': order,
                           'locator': {'fact_id': fact, 'dataset': 'FinQA',
                                       'quote_sha256': hashlib.sha256(text.encode()).hexdigest()}})
    doc = {'doc_id': qid, 'domain': 'financial_reports', 'source_title': qid.rsplit('-', 1)[0]}
    return question, doc, candidates


def prepare_finqa(source, out):
    if out.exists():
        raise FileExistsError(out)
    data = json.loads(source.read_text())
    questions, docs, candidates, gold = [], [], [], []
    seen = set()
    for row in data:
        q, doc, units = finqa_inputs(row)
        if q['qid'] in seen:
            raise ValueError('Duplicate FinQA id: ' + q['qid'])
        seen.add(q['qid'])
        # Evaluation-only labels are written into their own file. Verify that
        # they reference the inference units; never silently drop bad examples.
        facts = sorted(row['qa']['gold_inds'])
        present = {u['locator']['fact_id'] for u in units if u['text'].strip()}
        if not facts or set(facts) - present:
            raise ValueError('Empty/unmapped gold facts: ' + q['qid'])
        gold.append({'qid': q['qid'], 'company': q['qid'].split('/')[0],
                     'report': '/'.join(q['qid'].split('/')[:2]), 'facts': facts})
        questions.append(q)
        docs.append(doc)
        candidates.extend(units)
    if not questions:
        raise ValueError('Empty dataset')
    out.mkdir(parents=True)
    for name, rows in [('questions', questions), ('docs', docs), ('selector', candidates), ('gold', gold)]:
        write_jsonl(out / (name + '.jsonl'), rows)
    manifest = {'dataset': 'FinQA', 'upstream_commit': FINQA_COMMIT,
                'source_sha256': digest(source), 'questions': len(questions),
                'companies': len({g['company'] for g in gold}), 'candidates': len(candidates),
                'candidate_scope': 'one provided context per question; not full reports',
                'gold_in_inference': False, 'answer_values_imported': False,
                'files_sha256': {p.name: digest(p) for p in sorted(out.glob('*.jsonl'))}}
    write_json(out / 'manifest.json', manifest)
    return manifest


def start_run(data, out, protocol, experiment):
    if out.exists():
        raise FileExistsError('Preserve earlier runs; choose a new output directory')
    out.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    snapshot = out / 'source_snapshot'
    snapshot.mkdir()
    hashes = {}
    for package in ('agent', 'evidence_lab'):
        (snapshot / package).mkdir()
        for path in sorted((root / package).glob('*.py')):
            relative = path.relative_to(root)
            shutil.copy2(path, snapshot / relative)
            hashes[str(relative)] = digest(path)
    shutil.copy2(protocol, out / 'protocol.json')
    write_json(out / 'run_manifest.json', {
        'experiment': experiment, 'python': platform.python_version(), 'platform': platform.platform(),
        'protocol_sha256': digest(protocol), 'source_sha256': hashes,
        'data_sha256': {p.name: digest(p) for p in sorted(data.glob('*.jsonl'))},
        'api_calls': 0, 'answer_accuracy': None})


def load_inputs(data):
    # Deliberately cannot access gold.jsonl.
    qs = [Question.from_row(q) for q in read_jsonl(data / 'questions.jsonl')]
    if not qs:
        raise ValueError('Empty questions')
    index = CachedIndex.from_paths(data / 'selector.jsonl', data / 'docs.jsonl', enable_raw_fallback=False)
    return qs, index


def afac_ablation(data, out, protocol):
    start_run(data, out, protocol, 'afac_ablation')
    qs, index = load_inputs(data)
    rows = []
    started = time.perf_counter()
    for i, q in enumerate(qs):
        options, stem, _, missing = retrieve(index, q)
        if missing:
            raise ValueError('Missing requested docs: ' + q.qid)
        for variant in AFAC_VARIANTS:
            opts, question_rows = options, stem
            if variant == 'no_option_queries':
                opts, question_rows, _, _ = retrieve(index, q, include_options=False)
            selected, info = pack(q, opts, question_rows, Budget(),
                prioritize_docs=variant not in ('no_doc_priority', 'no_coverage_priority'),
                prioritize_options=variant not in ('no_option_priority', 'no_coverage_priority'),
                normalize_cost=variant != 'no_cost_normalization')
            rows.append({'qid': q.qid, 'domain': q.domain, 'variant': variant,
                         'requested_doc_complete': not info['missing_documents'],
                         'option_route_complete': not info['missing_option_routes'],
                         'missing_documents': info['missing_documents'],
                         'missing_option_routes': info['missing_option_routes'],
                         'prompt_chars': info['prompt_chars'], 'evidence_count': len(selected),
                         'candidate_ids': [r['candidate_id'] for r in selected]})
        if i % 20 == 0:
            print(f'AFAC {i + 1}/{len(qs)}', flush=True)
    write_jsonl(out / 'rows.jsonl', rows)
    def aggregate(items):
        return {'n': len(items),
                'doc_complete_count': sum(r['requested_doc_complete'] for r in items),
                'route_complete_count': sum(r['option_route_complete'] for r in items),
                'mean_prompt_chars': statistics.mean(r['prompt_chars'] for r in items),
                'mean_evidence_count': statistics.mean(r['evidence_count'] for r in items),
                'budget_violations': sum(r['prompt_chars'] > 12000 for r in items)}
    summary = {'questions': len(qs), 'variants': {}, 'by_domain': {},
               'scope': 'known A-list regression; route coverage is not gold evidence recall',
               'answer_accuracy': None, 'api_calls': 0, 'elapsed_seconds': time.perf_counter() - started}
    reference = {r['qid']: r for r in rows if r['variant'] == 'full'}
    for variant in AFAC_VARIANTS:
        items = [r for r in rows if r['variant'] == variant]
        metrics = aggregate(items)
        metrics['doc_wins_vs_full'] = sum(r['requested_doc_complete'] > reference[r['qid']]['requested_doc_complete'] for r in items)
        metrics['doc_losses_vs_full'] = sum(r['requested_doc_complete'] < reference[r['qid']]['requested_doc_complete'] for r in items)
        summary['variants'][variant] = metrics
        summary['by_domain'][variant] = {domain: aggregate([r for r in items if r['domain'] == domain])
                                        for domain in sorted({q.domain for q in qs})}
    write_json(out / 'summary.json', summary)
    return summary


def retrieval_metrics(predictions, facts):
    gold = set(facts)
    if not gold:
        raise ValueError('No gold evidence')
    result = {}
    for k in (3, 5):
        found = set(predictions[:k]) & gold
        result[f'recall_at_{k}'] = len(found) / len(gold)
        result[f'all_at_{k}'] = int(found == gold)
    return result


def paired_cluster_interval(rows, variant, metric, repeats=2000, seed=20260930):
    """Company-cluster paired percentile bootstrap; difference = variant-full.

    Each sampled company brings all its questions (unequal sizes preserved).
    Intervals are exploratory, pointwise, not multiplicity-adjusted tests.
    """
    reference = {r['qid']: r for r in rows if r['variant'] == 'full'}
    groups = defaultdict(list)
    for r in rows:
        if r['variant'] == variant:
            groups[r['company']].append(r[metric] - reference[r['qid']][metric])
    if not groups:
        raise ValueError('No paired samples')
    totals = [(sum(groups[k]), len(groups[k])) for k in sorted(groups)]
    rng, samples = random.Random(seed), []
    for _ in range(repeats):
        selected = [rng.choice(totals) for _ in totals]
        samples.append(sum(s for s, n in selected) / sum(n for s, n in selected))
    samples.sort()
    return {'difference': sum(s for s, n in totals) / sum(n for s, n in totals),
            'ci95': [samples[int(.025 * (repeats - 1))], samples[int(.975 * (repeats - 1))]],
            'clusters': len(totals), 'bootstrap_repeats': repeats, 'seed': seed}


def finqa_evaluate(data, out, protocol):
    start_run(data, out, protocol, 'finqa_external_retrieval')
    qs, index = load_inputs(data)
    predictions = []
    for i, q in enumerate(qs):
        for variant in FINQA_VARIANTS:
            _, ranked, _, missing = retrieve(index, q, question_top_k=5, scoring=variant)
            if missing:
                raise ValueError('Missing context: ' + q.qid)
            predictions.append({'qid': q.qid, 'variant': variant,
                                'predicted_facts': [r.candidate.locator['fact_id'] for r in ranked]})
        if i % 200 == 0:
            print(f'FinQA {i + 1}/{len(qs)}', flush=True)
    # Persist and hash predictions BEFORE loading labels for scoring.
    write_jsonl(out / 'predictions.jsonl', predictions)
    gold = {r['qid']: r for r in read_jsonl(data / 'gold.jsonl')}
    if set(gold) != {q.qid for q in qs}:
        raise ValueError('Gold/prediction ID mismatch')
    rows = []
    for r in predictions:
        g = gold[r['qid']]
        kinds = {f.split('_')[0] for f in g['facts']}
        row = {**r, 'company': g['company'], 'report': g['report'], 'gold_facts': g['facts'],
               'evidence_type': next(iter(kinds)) if len(kinds) == 1 else 'mixed',
               **retrieval_metrics(r['predicted_facts'], g['facts'])}
        rows.append(row)
    write_jsonl(out / 'rows.jsonl', rows)
    def aggregate(items):
        return {'n': len(items), **{key: statistics.mean(r[key] for r in items)
                for key in ('recall_at_3', 'recall_at_5', 'all_at_3', 'all_at_5')}}
    summary = {'questions': len(qs), 'variants': {}, 'by_evidence_type': {}, 'paired_vs_full': {},
               'prediction_sha256': digest(out / 'predictions.jsonl'), 'api_calls': 0, 'answer_accuracy': None,
               'scope': 'provided-context English retrieval; exact gold fact IDs, not answer correctness'}
    for variant in FINQA_VARIANTS:
        items = [r for r in rows if r['variant'] == variant]
        summary['variants'][variant] = aggregate(items)
        summary['by_evidence_type'][variant] = {kind: aggregate([r for r in items if r['evidence_type'] == kind])
                                                for kind in sorted({r['evidence_type'] for r in items})}
        if variant != 'full':
            summary['paired_vs_full'][variant] = paired_cluster_interval(rows, variant, 'all_at_5')
    write_json(out / 'summary.json', summary)
    return summary


def cache_evaluate(data, out, protocol, repeats=3):
    if repeats < 1:
        raise ValueError('At least one warm pass required')
    start_run(data, out, protocol, 'finqa_cache_equivalence')
    qs, fast = load_inputs(data)
    slow = CandidateIndex(fast.candidates_by_doc, fast.docs_by_id)
    timing, checks = [], []
    for repeat in range(repeats + 1):
        for i, q in enumerate(qs):
            calls = [('upstream', baseline, slow), ('cached', retrieve, fast)]
            if (i + repeat) % 2:
                calls.reverse()
            outputs = {}
            for name, func, index in calls:
                started = time.perf_counter()
                outputs[name] = func(index, q)
                timing.append({'pass': repeat, 'qid': q.qid, 'variant': name,
                               'seconds': time.perf_counter() - started})
            equal = signature(outputs['upstream']) == signature(outputs['cached'])
            checks.append({'pass': repeat, 'qid': q.qid, 'exact_equal': equal})
            if not equal:
                raise AssertionError('Cache changed retrieval output: ' + q.qid)
        print(f'Cache pass {repeat}/{repeats} complete', flush=True)
    write_jsonl(out / 'timing.jsonl', timing)
    write_jsonl(out / 'checks.jsonl', checks)
    warm = {name: sum(r['seconds'] for r in timing if r['variant'] == name and r['pass']) / repeats
            for name in ('upstream', 'cached')}
    summary = {'questions': len(qs), 'exact_equivalent_comparisons': len(checks),
               'all_equal': all(r['exact_equal'] for r in checks), 'warm_repeats': repeats,
               'warm_seconds_per_pass': warm, 'warm_speedup': warm['upstream'] / warm['cached'],
               'cold_seconds': {name: sum(r['seconds'] for r in timing if r['variant'] == name and not r['pass'])
                                for name in warm}, 'api_calls': 0}
    write_json(out / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare-finqa')
    prepare.add_argument('--source', type=Path, required=True)
    prepare.add_argument('--out', type=Path, required=True)
    for name in ('afac', 'finqa', 'cache'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--data', type=Path, required=True)
        cmd.add_argument('--out', type=Path, required=True)
        cmd.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare-finqa':
        result = prepare_finqa(args.source, args.out)
    else:
        fn = {'afac': afac_ablation, 'finqa': finqa_evaluate, 'cache': cache_evaluate}[args.command]
        result = fn(args.data, args.out, args.protocol)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
