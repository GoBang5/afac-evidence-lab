"""Fixed-protocol offline A-list comparison. No labels, API calls or tuning."""
from __future__ import annotations
import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from agent.domain_rules import extract_question_features, build_option_queries
from agent.io_utils import read_jsonl, write_json, write_jsonl
from agent.packer import pack_evidence
from agent.retrieval import CandidateIndex, retrieve_option_evidence, retrieve_question_evidence
from agent.schema import AgentConfig, Question
from .budget import Budget, pack, prompt_chars
from .data import digest
from .retrieval import CachedIndex, retrieve


def baseline(index, q):
    features = extract_question_features(q)
    docs, missing = index.route_docs(q, 16)
    options = retrieve_option_evidence(index, q, features, docs, build_option_queries(q, features), 6)
    query = '\n'.join([q.question, ' '.join(features.keyphrases), ' '.join(features.domain_terms)])
    stem = retrieve_question_evidence(index, q, features, docs, query, 14)
    return options, stem, docs, missing


def signature(result):
    options, stem, docs, missing = result
    return {'docs': docs, 'missing': missing,
            'options': {k: [r.to_row(900) for r in v] for k, v in options.items()},
            'stem': [r.to_row(900) for r in stem]}


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * p))]


def evaluate(data, out, repeats=3, limit=None):
    if repeats < 1:
        raise ValueError('repeats must be positive')
    if out.exists():
        raise FileExistsError('Use a new output directory to preserve earlier experiments')
    qs = [Question.from_row(q) for q in read_jsonl(data / 'questions.jsonl')]
    if limit is not None:
        qs = qs[:limit]
    if not qs:
        raise ValueError('No questions')
    out.mkdir(parents=True)
    root = Path(__file__).parents[1]
    protocol = {'upstream_commit': '042e0fdb27be88692d05451198bb1be38a152aeb',
                'questions': len(qs), 'warm_repeats': repeats, 'python': platform.python_version(),
                'platform': platform.platform(), 'option_top_k': 6, 'question_top_k': 14,
                'max_prompt_chars': 12000, 'max_evidence': 18, 'max_quote_chars': 900,
                'source_hashes': {str(p.relative_to(root)): digest(p) for d in ('agent', 'evidence_lab') for p in sorted((root / d).glob('*.py'))},
                'data_hashes': {n: digest(data / n) for n in ('selector.jsonl', 'docs.jsonl', 'questions.jsonl')},
                'labels': 'none: no answer accuracy or gold evidence recall can be measured',
                'comparison': 'Unchanged score formula; same inputs; alternating order; warm cache timings exclude packing/loading; one cold pass includes lazy cache fill',
                'packing_baseline': 'upstream packer, then drop tail rows until same full-message character budget fits'}
    write_json(out / 'protocol.json', protocol)
    idx = CandidateIndex.from_paths(data / 'selector.jsonl', data / 'docs.jsonl', enable_raw_fallback=False)
    fast = CachedIndex(idx.candidates_by_doc, idx.docs_by_id)
    rows, timing, cold = [], {'upstream': [], 'cached': []}, {'upstream': 0.0, 'cached': 0.0}
    all_equal = True
    for repetition in range(repeats + 1):
        totals = {'upstream': 0.0, 'cached': 0.0}
        for i, q in enumerate(qs):
            values, durations = {}, {}
            order = [('upstream', baseline, idx), ('cached', retrieve, fast)]
            if (i + repetition) % 2:
                order.reverse()
            for name, fn, index in order:
                start = time.perf_counter()
                values[name] = fn(index, q)
                durations[name] = time.perf_counter() - start
                totals[name] += durations[name]
                if repetition:
                    timing[name].append(durations[name])
            equal = signature(values['upstream']) == signature(values['cached'])
            all_equal &= equal
            if repetition == 0:
                options, stem, _, _ = values['upstream']
                _, unbounded = pack_evidence(options, stem, AgentConfig())
                original_chars = prompt_chars(q, unbounded)
                bounded = list(unbounded)
                while bounded and prompt_chars(q, bounded) > 12000:
                    bounded.pop()
                optimized, info = pack(q, options, stem, Budget())
                def full_doc_coverage(items):
                    return bool(q.doc_ids) and set(q.doc_ids) <= {r['doc_id'] for r in items}
                rows.append({'qid': q.qid, 'domain': q.domain, 'score_and_rank_equal': equal,
                             'original_prompt_chars': original_chars,
                             'baseline_prompt_chars': prompt_chars(q, bounded),
                             'optimized_prompt_chars': info['prompt_chars'],
                             'baseline_full_doc_coverage': full_doc_coverage(bounded),
                             'optimized_full_doc_coverage': full_doc_coverage(optimized),
                             'optimized_missing_option_routes': info['missing_option_routes'],
                             'baseline_ids': [r['candidate_id'] for r in bounded],
                             'optimized_ids': [r['candidate_id'] for r in optimized]})
            if i % 20 == 0:
                print(f'pass={repetition} questions={i + 1}/{len(qs)}', flush=True)
        if repetition == 0:
            cold = totals
        else:
            write_json(out / f'timing-pass-{repetition}.json', totals)
    summary = {'questions': len(qs), 'score_and_rank_equal_all_passes': all_equal,
               'cold_retrieval_seconds': cold,
               'warm_retrieval_seconds_per_pass': {k: sum(v) / repeats for k, v in timing.items()},
               'warm_query_p50_ms': {k: statistics.median(v) * 1000 for k, v in timing.items()},
               'warm_query_p95_ms': {k: percentile(v, .95) * 1000 for k, v in timing.items()},
               'warm_speedup': sum(timing['upstream']) / sum(timing['cached']),
               'upstream_over_budget_questions': sum(r['original_prompt_chars'] > 12000 for r in rows),
               'optimized_over_budget_questions': sum(r['optimized_prompt_chars'] > 12000 for r in rows),
               'baseline_full_doc_coverage': sum(r['baseline_full_doc_coverage'] for r in rows),
               'optimized_full_doc_coverage': sum(r['optimized_full_doc_coverage'] for r in rows),
               'optimized_complete_option_routes': sum(not r['optimized_missing_option_routes'] for r in rows),
               'mean_prompt_chars': {k: statistics.mean(r[k + '_prompt_chars'] for r in rows) for k in ('original', 'baseline', 'optimized')},
               'answer_accuracy': None, 'api_calls': 0, 'model_tokens': 0}
    write_json(out / 'summary.json', summary)
    write_jsonl(out / 'rows.jsonl', rows)
    write_json(out / 'latencies.json', timing)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not all_equal or summary['optimized_over_budget_questions']:
        raise RuntimeError('Benchmark invariants failed')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--limit', type=int)
    a = p.parse_args()
    evaluate(a.data, a.out, a.repeats, a.limit)
