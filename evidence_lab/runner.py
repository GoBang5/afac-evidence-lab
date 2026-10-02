"""Resumable retrieve/pack/judge/audit pipeline with an explicit offline mode."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import json
import time
from collections import Counter

from agent.io_utils import read_jsonl, write_json, write_jsonl
from agent.judge import make_judge
from agent.schema import AgentConfig, Question
from .budget import Budget
from .checkpoint import Checkpoints, fingerprint
from .data import digest
from .retrieval import CachedIndex
from .api_config import read_config
from .client import CachedCompletion
from .numeric import NumericConfig
from .workflow import run_question


def run(data, output, budget=Budget(), config=None, limit=None, *, api_config=None,
        numeric=NumericConfig(), max_requests=100, request_cache=None):
    data, output = Path(data), Path(output)
    config = config or AgentConfig()
    if not 0 <= config.max_repair_rounds <= 3 or config.repair_top_k < 1:
        raise ValueError('Invalid repair limits')
    local = read_config(api_config) if api_config is not None and config.judge_mode != 'none' else None
    if local:
        config = replace(config, llm_model=local['API_MODEL'], llm_base_url=local['API_BASE_URL'])
    if config.judge_mode == 'qwen' and not config.allow_qwen:
        # Preserve the upstream explicit Qwen gate for both task types.
        local = None
    if config.judge_mode not in ('none', 'qwen', 'openai_compatible'):
        raise ValueError('Lab accepts fresh model judgements or offline mode only')
    if config.env_file:
        raise ValueError('Use api_config with API_* fields, not the upstream env_file format')
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
        'repair': {'rounds': config.max_repair_rounds, 'top_k': config.repair_top_k},
        'numeric': asdict(numeric), 'max_requests': max_requests,
    }
    key = fingerprint(identity)
    request_identity = fingerprint({'sources': sources, 'endpoint': config.llm_base_url, 'model': config.llm_model})
    request_path = Path(request_cache) if request_cache else output / 'requests.sqlite'
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
    index = judge = complete = None
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
                if question.answer_format == 'numeric':
                    if config.judge_mode != 'none' and complete is None:
                        if local is None:
                            raise ValueError('Numeric model mode requires local API config and Qwen authorization when applicable')
                        complete = CachedCompletion(local, request_path, request_identity,
                                                    max_requests, budget.max_prompt_chars)
                elif judge is None:
                    if local:
                        from .local_judge import LocalJudge
                        if complete is None:
                            complete = CachedCompletion(local, request_path, request_identity,
                                                        max_requests, budget.max_prompt_chars)
                        judge = LocalJudge(complete, config)
                    else:
                        judge = make_judge(config.judge_mode, config=config)
                result = run_question(question, index, judge, budget, config, complete, numeric)
                store.put(question.qid, result)
                results.append(result)
            except Exception as exc:
                # Retry failed questions on the next invocation; don't cache failure as success.
                failures.append({'qid': question.qid, 'error_type': type(exc).__name__})
                if complete is not None:
                    # Stop the batch on transport/quota/unknown-outcome failures.
                    break
    finally:
        store.close()
        if complete is not None:
            complete.close()
    summary = {'questions_requested': len(questions), 'completed': len(results), 'reused': reused,
               'failures': failures, 'elapsed_seconds': time.perf_counter() - start,
               'status': dict(Counter(r['status'] for r in results)),
               'total_tokens': sum(r['judge']['total_tokens'] for r in results),
               'answer_accuracy': None, 'mode': config.judge_mode, 'fingerprint': key,
               'new_model_requests': complete.new_calls if complete else 0,
               'repair_rounds': sum(r.get('repair_rounds', 0) for r in results)}
    write_jsonl(output / 'questions.jsonl', results)
    write_json(output / 'summary.json', summary)
    return summary
