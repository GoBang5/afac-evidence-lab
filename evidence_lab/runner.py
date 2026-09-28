"""Resumable retrieve/pack/judge/audit pipeline with an explicit offline mode."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import time
from collections import Counter

from agent.io_utils import read_jsonl, write_json, write_jsonl
from agent.judge import make_judge
from agent.schema import AgentConfig, Question
from .audit import validate
from .budget import Budget, pack
from .checkpoint import Checkpoints, fingerprint
from .data import digest
from .retrieval import CachedIndex, retrieve


def run(data, output, budget=Budget(), config=None, limit=None):
    data, output = Path(data), Path(output)
    config = config or AgentConfig()
    if config.judge_mode not in ('none', 'qwen', 'openai_compatible'):
        raise ValueError('Lab accepts fresh model judgements or offline mode only')
    if config.env_file:
        raise ValueError('Lab uses environment variables only, not credential files')
    if config.judge_mode != 'none' and not (config.llm_model and config.llm_base_url):
        raise ValueError('Explicit model and endpoint required for cache identity')
    sources = {str(p.relative_to(Path(__file__).parents[1])): digest(p)
               for directory in ('evidence_lab', 'agent')
               for p in sorted((Path(__file__).parents[1] / directory).glob('*.py'))}
    identity = {
        'data': {name: digest(data / name) for name in ('selector.jsonl', 'docs.jsonl', 'questions.jsonl')},
        'sources': sources, 'budget': asdict(budget),
        'judge': {k: getattr(config, k) for k in ('judge_mode', 'llm_model', 'llm_base_url', 'llm_temperature', 'llm_max_tokens')},
        'retrieval': {'option_top_k': config.option_top_k, 'question_top_k': config.question_top_k, 'doc_top_k_b': config.doc_top_k_b},
    }
    key = fingerprint(identity)
    output.mkdir(parents=True, exist_ok=True)
    # Do not overwrite an earlier run with a different configuration or source.
    manifest_path = output / 'run_manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text())['fingerprint'] != key:
        raise ValueError('Output already belongs to different code/data/config; choose a new output')
    write_json(manifest_path, {'fingerprint': key, **identity})
    questions = [Question.from_row(q) for q in read_jsonl(data / 'questions.jsonl')]
    if len({q.qid for q in questions}) != len(questions) or any(not q.qid for q in questions):
        raise ValueError('Question IDs must be unique and nonempty')
    if limit is not None:
        questions = questions[:limit]
    store = Checkpoints(output / 'checkpoints.sqlite', key)
    index = judge = None
    results, reused, failures = [], 0, []
    start = time.perf_counter()
    try:
        for question in questions:
            cached = store.get(question.qid)
            if cached is not None:
                results.append(cached)
                reused += 1
                continue
            try:
                if index is None:
                    index = CachedIndex.from_paths(data / 'selector.jsonl', data / 'docs.jsonl', enable_raw_fallback=False)
                if judge is None:
                    judge = make_judge(config.judge_mode, config=config)
                options, stem, docs, missing = retrieve(index, question, config.option_top_k, config.question_top_k, config.doc_top_k_b)
                evidence, packing = pack(question, options, stem, budget)
                judgement = judge.judge(question, evidence)
                answer, status, flags = validate(question, evidence, judgement)
                if missing or packing['missing_documents'] or packing['missing_option_routes']:
                    flags.append('incomplete_retrieval_coverage')
                    if config.judge_mode != 'none':
                        status = 'needs_review'
                result = {'qid': question.qid, 'domain': question.domain, 'answer': answer,
                          'status': status, 'flags': flags, 'candidate_docs': docs,
                          'packing': packing, 'evidence': evidence, 'judge': asdict(judgement)}
                store.put(question.qid, result)
                results.append(result)
            except Exception as exc:
                # Retry failed questions on the next invocation; don't cache failure as success.
                failures.append({'qid': question.qid, 'error_type': type(exc).__name__})
    finally:
        store.close()
    summary = {'questions_requested': len(questions), 'completed': len(results), 'reused': reused,
               'failures': failures, 'elapsed_seconds': time.perf_counter() - start,
               'status': dict(Counter(r['status'] for r in results)),
               'total_tokens': sum(r['judge']['total_tokens'] for r in results),
               'answer_accuracy': None, 'mode': config.judge_mode, 'fingerprint': key}
    write_jsonl(output / 'questions.jsonl', results)
    write_json(output / 'summary.json', summary)
    return summary
