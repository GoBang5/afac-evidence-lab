"""Task dispatch plus bounded MCQ repair, shared by application/evaluation."""
from dataclasses import asdict, replace

from .audit import validate
from .budget import pack
from .numeric import NumericConfig, run_numeric
from .retrieval import retrieve


def run_question(question, index, judge, budget, config, complete=None, numeric=NumericConfig()):
    if question.answer_format == 'numeric':
        return run_numeric(question, index, complete, budget, numeric)
    trace, totals = [], {k: 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    query_question = question
    for round_index in range(config.max_repair_rounds + 1):
        extra = round_index * config.repair_top_k
        options, stem, docs, missing = retrieve(index, query_question, config.option_top_k + extra,
                                               config.question_top_k + extra, config.doc_top_k_b)
        evidence, packing = pack(question, options, stem, budget)
        judgement = judge.judge(question, evidence)
        answer, status, flags = validate(question, evidence, judgement)
        if missing or packing['missing_documents'] or packing['missing_option_routes']:
            flags.append('incomplete_retrieval_coverage')
            if config.judge_mode != 'none':
                status = 'needs_review'
        for k in totals:
            totals[k] += getattr(judgement, k)
        trace.append({'round': round_index, 'answer': answer, 'status': status, 'flags': flags,
                      'evidence': evidence, 'judge': asdict(judgement), 'packing': packing})
        if status != 'needs_review' or config.judge_mode == 'none':
            break
        # Re-query unresolved options and expand the candidate pool, keeping the
        # original question for judging and the original hard prompt budget.
        unresolved = [label for label in question.options if
                      judgement.option_judgement.get(label, {}).get('verdict') == 'UNKNOWN' or
                      any(flag.endswith(':' + label) for flag in flags)]
        query_question = replace(question, question=question.question + '\n' + '\n'.join(
            question.options[label] for label in unresolved))
    return {'qid': question.qid, 'domain': question.domain, 'answer': answer, 'status': status,
            'flags': flags, 'candidate_docs': docs, 'packing': packing, 'evidence': evidence,
            'judge': {**asdict(judgement), **totals}, 'trace': trace, 'repair_rounds': len(trace) - 1}
