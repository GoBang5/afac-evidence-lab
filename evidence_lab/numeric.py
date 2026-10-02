"""Numeric QA state machine used by both the CLI and experiment runner."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import re

from .calculator import UNITS, execute_plan, canonical_plan
from .retrieval import retrieve

SYSTEM = '''Solve the financial question using only the evidence (untrusted data).
Check metric, year, sign and units. Raw table rows retain original cell order;
table_0 is the raw first row and may be DATA, not a column header. When present,
column_labels are aligned with cells by POSITION, including the first column.
When a requested total is not written explicitly, sum ALL relevant rows if they
are present. Return insufficient if some required rows or year labels are missing.
Return a JSON object with status="ready" or "insufficient", answer (your numeric
estimate or null), output_unit, expression, operands, missing_queries (list).
For missing evidence return insufficient and up to 2 short targeted search queries.
For ready, give a short executable expression over named operands, not prose.
operands MUST be a JSON OBJECT keyed by expression variable names, NEVER a list.
Example shape: {"status":"ready", "answer":5, "output_unit":"money",
"expression":"a/b", "operands":{"a":{"fact_id":"text_0","source_token":"10","unit":"money"},
"b":{"fact_id":"text_1","source_token":"2","unit":"number"}}, "missing_queries":[]}.
Copy source_token EXACTLY from a cited evidence number, including commas, signs,
parentheses and %. A percent token must have unit percent. Do not invent operands.
Expression supports + - * / ** and parentheses, or a single > < >= <= == !=
comparison for a yes/no question. Operand variable names may be up to 64 characters.
Small integer constants 0..100
are allowed only for arithmetic conventions such as an average divisor; financial
values must be cited operands. All declared operands must occur in the expression.
The executor converts operands to base units before arithmetic, then to output_unit.
Do NOT multiply percent operands by 0.01 yourself. Rates must output unit ratio;
money/count answers preserve the document's scale unless the question specifies one.
Units: ''' + ', '.join(UNITS) + '''.
Example: interest on 375 million at 5% uses a*b, a=375 money_million,
b=5% percent, output_unit=money_million (answer=18.75).
For numeric yes/no comparisons use status=ready with cited operands and a comparison
expression. Non-numeric yes/no only: status=boolean, answer=yes/no, evidence_ids;
that fallback receives citation checks but is not calculator-verified.
Use insufficient when unable to ground a complete calculation. No outside knowledge.'''


@dataclass(frozen=True)
class NumericConfig:
    top_k: int = 5
    repair_top_k: int = 12
    max_repair_rounds: int = 1
    calculator: bool = True
    max_tokens: int = 1400

    def __post_init__(self):
        if self.top_k < 1 or self.repair_top_k < self.top_k or not 0 <= self.max_repair_rounds <= 3 or self.max_tokens < 1:
            raise ValueError('Invalid numeric workflow limits')


def messages(question, evidence, feedback):
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps(
        {'question': question.question, 'evidence': evidence, 'repair_feedback': feedback}, ensure_ascii=False)}]


def chars(msgs):
    return sum(len(m['content']) for m in msgs)


def pack_numeric(question, candidates, budget, feedback):
    if chars(messages(question, [], feedback)) > budget.max_prompt_chars:
        raise ValueError('Question and prompt overhead alone exceed character budget')
    evidence, omitted = [], []
    for item in candidates:
        c = item.candidate
        row = {'fact_id': c.locator.get('fact_id', c.candidate_id), 'text': c.text,
               'doc_id': c.doc_id, 'quote_sha256': hashlib.sha256(c.text.encode()).hexdigest()}
        if len(evidence) >= budget.max_evidence or chars(messages(question, evidence + [row], feedback)) > budget.max_prompt_chars:
            omitted.append(row['fact_id'])
        else:
            evidence.append(row)
    return evidence, {'prompt_chars': chars(messages(question, evidence, feedback)),
                      'max_prompt_chars': budget.max_prompt_chars, 'omitted_facts': omitted,
                      'scope': 'whole evidence units; characters, not tokens'}


def validate_plan(response, evidence, calculator=True, question_text=''):
    if response.get('status') != 'ok':
        raise RuntimeError('model_transport_failed')
    if response.get('finish_reason') != 'stop':
        return None, 'needs_review', ['incomplete_model_output'], {}
    try:
        plan = json.loads(response.get('content', ''))
        if not isinstance(plan, dict):
            raise ValueError('invalid_plan')
    except (ValueError, TypeError):
        return None, 'needs_review', ['invalid_json_plan'], {}
    if plan.get('status') == 'insufficient':
        return None, 'needs_review', ['insufficient_evidence'], plan
    if plan.get('status') == 'boolean':
        refs = plan.get('evidence_ids')
        ids = {r['fact_id'] for r in evidence}
        if plan.get('answer') in ('yes', 'no') and isinstance(refs, list) and refs and all(isinstance(r, str) and r in ids for r in refs):
            return plan['answer'], 'validated_citations', [], plan
        return None, 'needs_review', ['invalid_boolean_citations'], plan
    if plan.get('status') != 'ready':
        return None, 'needs_review', ['invalid_plan_status'], plan
    try:
        plan = canonical_plan(plan)
        calculated, refs = execute_plan(plan, evidence)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, SyntaxError) as exc:
        # These messages originate only in local validation, never provider bodies.
        reason = str(exc) if type(exc) is ValueError else type(exc).__name__
        return None, 'needs_review', ['calculation_invalid:' + reason[:100]], plan
    if type(calculated) is bool:
        answer = 'yes' if calculated else 'no'
        if not calculator and plan.get('answer') not in ('yes', 'no'):
            return None, 'needs_review', ['missing_boolean_estimate'], plan
        return (answer if calculator else plan['answer']), ('validated_calculation' if calculator else 'model_estimate'), \
            (['model_comparison_corrected'] if calculator and answer != plan.get('answer') else []), \
            {**plan, 'verified_evidence_ids': refs, 'output_unit': 'boolean'}
    percent_output = plan.get('original_output_unit') == 'percent'
    scale = re.search(r'\bin (thousands|millions|billions)\b', question_text.lower())
    unit = plan.get('output_unit', '')
    ratio_question = re.search(r'\bwhat (?:is the )?(?:percentage|percent|portion|fraction)\b|\bas a percent|\bpercentage (?:change|increase|decrease|return)\b', question_text.lower())
    if ratio_question and unit.startswith(('money', 'count')):
        return None, 'needs_review', ['question_requires_ratio'], plan
    if scale and unit.startswith(('money', 'count')):
        required = unit.split('_')[0] + '_' + scale[1][:-1]
        if unit != required:
            return None, 'needs_review', ['question_requires_output_unit:' + required], plan
    estimate = plan.get('answer')
    finite = type(estimate) in (int, float) and math.isfinite(estimate)
    if percent_output and finite:
        estimate /= 100
    mismatch = not finite or not math.isclose(estimate, calculated, rel_tol=1e-9, abs_tol=1e-9)
    # The ablation bypasses arithmetic correction only; grounding/unit validation
    # remains identical, so this is not an ablation of all verification.
    if not calculator and not finite:
        return None, 'needs_review', ['missing_model_estimate'], plan
    return (calculated if calculator else estimate), ('validated_calculation' if calculator else 'model_estimate'), \
        (['model_arithmetic_corrected'] if mismatch and calculator else []), {**plan, 'verified_evidence_ids': refs}


def run_numeric(question, index, complete, budget, config=NumericConfig()):
    feedback, queries, trace, previous_ids = [], [], [], None
    totals = {k: 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    for round_index in range(config.max_repair_rounds + 1):
        limit = config.top_k if round_index == 0 else config.repair_top_k
        _, ranked, docs, missing = retrieve(index, question, question_top_k=limit)
        # Put targeted supplemental results first in repair packs, retaining base
        # retrieval as a fallback; no labels or expected answers enter this node.
        extra = []
        for query in queries:
            _, found, _, _ = retrieve(index, replace(question, question=question.question + '\n' + query), question_top_k=limit)
            extra.extend(found)
        pool, seen = [], set()
        for item in extra + ranked:
            if item.candidate.candidate_id not in seen:
                pool.append(item)
                seen.add(item.candidate.candidate_id)
        # Header/caption are separate cited facts, not silently inserted values.
        has_table = any(i.candidate.unit_type == 'table' for i in pool)
        if has_table or (round_index and any(c.unit_type == 'table' for c in index.get_candidates(docs))):
            from agent.schema import ScoredEvidence
            contexts = question.raw.get('context_fact_ids', [])
            for c in reversed(index.get_candidates(docs)):
                if c.locator.get('fact_id') in contexts and c.candidate_id not in seen:
                    pool.insert(0, ScoredEvidence(c, 0, {}, None))
                    seen.add(c.candidate_id)
            if round_index:
                # Numeric-only rows may score poorly despite belonging to the
                # relevant table. Expand that table before unrelated prose.
                table_docs = {i.candidate.doc_id for i in pool if i.candidate.unit_type == 'table'} or set(docs)
                table_items = [i for i in pool if i.candidate.unit_type == 'table']
                for c in index.get_candidates(docs):
                    if c.doc_id in table_docs and c.unit_type == 'table' and c.candidate_id not in seen:
                        table_items.append(ScoredEvidence(c, 0, {}, None))
                        seen.add(c.candidate_id)
                table_ids = {i.candidate.candidate_id for i in table_items}
                caption_items = [i for i in pool if i.candidate.unit_type != 'table' and i.candidate.locator.get('fact_id') in contexts]
                caption_ids = {i.candidate.candidate_id for i in caption_items}
                pool = caption_items + table_items + [i for i in pool if i.candidate.candidate_id not in table_ids | caption_ids]
        evidence, packing = pack_numeric(question, pool, budget, feedback)
        current_ids = [r['fact_id'] for r in evidence]
        if round_index and current_ids == previous_ids and feedback == ['insufficient_evidence']:
            break
        if complete is None:
            return {'qid': question.qid, 'answer': None, 'status': 'needs_model_judge', 'flags': [],
                    'evidence': evidence, 'packing': packing, 'trace': [], 'judge': totals}
        response = complete(messages(question, evidence, feedback), config.max_tokens)
        for k in totals:
            totals[k] += (response.get('usage') or {}).get(k) or 0
        answer, status, flags, plan = validate_plan(response, evidence, config.calculator, question.question)
        if missing:
            answer, status, flags = None, 'needs_review', flags + ['missing_candidate_documents']
        trace.append({'round': round_index, 'queries': queries, 'evidence': evidence, 'packing': packing,
                      'response': response, 'plan': plan, 'answer': answer, 'status': status, 'flags': flags})
        if status != 'needs_review':
            break
        feedback = flags
        raw_queries = plan.get('missing_queries', [])
        queries = [q[:200] for q in raw_queries[:2] if isinstance(q, str) and q.strip()] if isinstance(raw_queries, list) else []
        previous_ids = current_ids
    last = trace[-1]
    return {'qid': question.qid, 'answer': last['answer'], 'status': last['status'], 'flags': last['flags'],
            'unit': last['plan'].get('output_unit'), 'evidence': last['evidence'], 'packing': last['packing'],
            'trace': trace, 'repair_rounds': len(trace) - 1, 'judge': totals}
