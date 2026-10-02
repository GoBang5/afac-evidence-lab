import copy
import json
from dataclasses import replace
from unittest.mock import patch

from agent.io_utils import read_jsonl, write_jsonl
from agent.schema import AgentConfig, JudgeOutput, Question
from evidence_lab.budget import Budget
from evidence_lab.calculator import execute_plan
from evidence_lab.client import CachedCompletion
from evidence_lab.numeric import NumericConfig, pack_numeric, run_numeric, validate_plan
from evidence_lab.retrieval import CachedIndex
from evidence_lab.runner import run
from evidence_lab.workflow_experiment import structured_inputs, prepare, run as experiment_run
from test_lab import TemporaryTest, candidate, DATA


def response(plan, finish='stop'):
    return {'status': 'ok', 'content': json.dumps(plan), 'finish_reason': finish,
            'served_model': 'test-model', 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


def plan(expression='a-b-c', answer=457):
    return {'status': 'ready', 'expression': expression, 'answer': answer, 'output_unit': 'money',
            'operands': {name: {'fact_id': 'table_1', 'source_token': token, 'unit': 'money'}
                         for name, token in [('a', '262'), ('b', '472'), ('c', '102')]}}


class CalculatorTests(TemporaryTest):
    def test_inconsistent_answer_replaced_by_executed_value(self):
        evidence = [{'fact_id': 'table_1', 'text': 'cash flows 262, expenses 472, other 102.'}]
        # Commas attached to numbers remain part of exact source_token.
        evidence[0]['text'] = 'cash flows 262 ; expenses 472 ; other 102.'
        answer, status, flags, _ = validate_plan(response(plan()), evidence)
        self.assertEqual(answer, -312)
        self.assertEqual(status, 'validated_calculation')
        self.assertIn('model_arithmetic_corrected', flags)
        ablated = validate_plan(response(plan()), evidence, calculator=False)
        self.assertEqual(ablated[:2], (457, 'model_estimate'))

    def test_currency_percent_and_output_scale(self):
        p = {'expression': 'a*b', 'output_unit': 'money_million', 'operands': {
            'a': {'fact_id': 'text_0', 'source_token': '375', 'unit': 'money_million'},
            'b': {'fact_id': 'text_0', 'source_token': '5%', 'unit': 'percent'}}}
        self.assertEqual(execute_plan(p, [{'fact_id': 'text_0', 'text': 'Debt 375 million at 5%.'}])[0], 18.75)
        p['operands']['b']['unit'] = 'number'
        with self.assertRaisesRegex(ValueError, 'percent_source'):
            execute_plan(p, [{'fact_id': 'text_0', 'text': 'Debt 375 million at 5%.'}])

    def test_parentheses_commas_and_unit_conversion(self):
        p = {'expression': 'a+b', 'output_unit': 'money_million', 'operands': {
            'a': {'fact_id': 'x', 'source_token': '(1,000)', 'unit': 'money_thousand'},
            'b': {'fact_id': 'x', 'source_token': '3', 'unit': 'money_million'}}}
        self.assertEqual(execute_plan(p, [{'fact_id': 'x', 'text': '(1,000) thousand plus 3 million'}])[0], 2)

    def test_hallucinated_amount_and_substring_rejected(self):
        for text in ('1262 472 102', '999 472 102'):
            with self.assertRaisesRegex(ValueError, 'operand_not_in'):
                execute_plan(plan(), [{'fact_id': 'table_1', 'text': text}])

    def test_unsafe_expression_zero_division_and_wrong_units_rejected(self):
        evidence = [{'fact_id': 'table_1', 'text': '262 ; 472 ; 102'}]
        for expression in ('__import__("os").getcwd()', 'a.__class__', '[a][0]', 'a/(b-b)+c', 'a**10000000+b+c'):
            with self.assertRaises((ValueError, SyntaxError)):
                execute_plan(plan(expression), evidence)
        p = plan(); p['operands']['b']['unit'] = 'count'
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            execute_plan(p, evidence)

    def test_truncated_json_and_bad_citation_never_accepted(self):
        self.assertIsNone(validate_plan(response(plan(), 'length'), [])[0])
        self.assertIsNone(validate_plan(response(plan()), [])[0])
        bad = {'status': 'boolean', 'answer': 'yes', 'evidence_ids': [['invalid']]}
        self.assertIsNone(validate_plan(response(bad), [])[0])

    def test_question_unit_constraint_and_punctuation_tokens(self):
        evidence = [{'fact_id': 'table_1', 'text': '262, 472, 102.'}]
        self.assertEqual(execute_plan(plan(), evidence)[0], -312)
        result = validate_plan(response(plan()), evidence, question_text='What is net cash in millions?')
        self.assertIsNone(result[0])
        self.assertEqual(result[2], ['question_requires_output_unit:money_million'])

    def test_percent_output_converted_to_ratio_without_model_retry(self):
        p = {'status': 'ready', 'expression': 'a/b', 'output_unit': 'percent', 'answer': 50,
             'operands': {'a': {'fact_id': 'x', 'source_token': '5', 'unit': 'number'},
                          'b': {'fact_id': 'x', 'source_token': '10', 'unit': 'number'}}}
        answer, status, _, result = validate_plan(response(p), [{'fact_id': 'x', 'text': '5 of 10'}])
        self.assertEqual(answer, .5)
        self.assertEqual(result['output_unit'], 'ratio')
        p['expression'] = '(a / b) * 100'
        self.assertEqual(validate_plan(response(p), [{'fact_id': 'x', 'text': '5 of 10'}])[0], .5)

    def test_descriptive_variables_boolean_and_ratio_question(self):
        p = {'status': 'ready', 'expression': 'very_long_descriptive_amount > second_amount', 'output_unit': 'number', 'answer': 'yes',
             'operands': {'very_long_descriptive_amount': {'fact_id': 'x', 'source_token': '5', 'unit': 'money'},
                          'second_amount': {'fact_id': 'x', 'source_token': '10', 'unit': 'money'}}}
        answer, status, flags, _ = validate_plan(response(p), [{'fact_id': 'x', 'text': '5 of 10'}])
        self.assertEqual(answer, 'no')
        self.assertIn('model_comparison_corrected', flags)
        p['expression'] = 'second_amount - very_long_descriptive_amount'
        p['output_unit'] = 'money'
        self.assertIsNone(validate_plan(response(p), [{'fact_id': 'x', 'text': '5 of 10'}], question_text='what portion is held here?')[0])


class WorkflowTests(TemporaryTest):
    def numeric_data(self):
        row = {'id': 'q', 'pre_text': ['Amounts in millions.'], 'post_text': [],
               'table': [['net tangible assets', '$ 23700'], ['developed technology', '1900'], ['purchase price', '31300']],
               'qa': {'question': 'What fraction is developed technology of purchase price?', 'exe_ans': .06,
                      'gold_inds': {'table_1': 'SECRET'}}}
        q, d, cs = structured_inputs(row)
        data = self.path / 'data'; data.mkdir()
        for name, rows in [('questions', [q]), ('docs', [d]), ('selector', cs)]:
            write_jsonl(data / (name + '.jsonl'), rows)
        return data, row

    def api(self):
        p = self.path / 'api.local.env'
        p.write_text('API_BASE_URL=https://mock.invalid/v1\nAPI_KEY=test-secret-key\nAPI_MODEL=test-model\n')
        return p

    def test_raw_table_preserved_without_fake_column_header(self):
        _, row = self.numeric_data()
        q, _, cs = structured_inputs(row)
        unit = next(c for c in cs if c['locator']['fact_id'] == 'table_1')
        self.assertEqual(json.loads(unit['text'])['cells'], ['developed technology', '1900'])
        self.assertNotIn('23700', unit['text'])
        self.assertIn('table_0', q['context_fact_ids'])
        changed = copy.deepcopy(row)
        changed['qa'].update(exe_ans='OTHER', gold_inds={'text_0': 'OTHER'}, program='OTHER')
        self.assertEqual(structured_inputs(row), structured_inputs(changed))
        self.assertNotIn('SECRET', json.dumps(structured_inputs(row)))

    def test_headers_align_year_columns_including_numeric_first_column(self):
        _, row = self.numeric_data()
        row['table'] = [['2011', '2010', '2009'], ['35', '29', '20']]
        _, _, units = structured_inputs(row)
        table = next(c for c in units if c['locator']['fact_id'] == 'table_1')
        self.assertEqual(json.loads(table['text'])['column_labels'], ['2011', '2010', '2009'])
        row['table'] = [['net tangible assets', '1900'], ['technology', '23']]
        _, _, units = structured_inputs(row)
        self.assertNotIn('column_labels', next(c['text'] for c in units if c['locator']['fact_id'] == 'table_1'))

    def test_repair_fetches_numeric_only_table_row_missing_from_rankings(self):
        data, _ = self.numeric_data()
        q = Question.from_row(read_jsonl(data / 'questions.jsonl')[0])
        q = replace(q, question='What was the developed technology amount?')
        index = CachedIndex.from_paths(data / 'selector.jsonl', data / 'docs.jsonl', enable_raw_fallback=False)
        # Simulate lexical retrieval never returning the needed numerical row.
        only_header = candidate('header', 'q', 'header')
        seen = []
        def complete(messages, max_tokens):
            evidence = json.loads(messages[1]['content'])['evidence']; seen.append(evidence)
            if len(seen) == 1:
                return response({'status': 'insufficient'})
            self.assertIn('table_1', {e['fact_id'] for e in evidence})
            return response({'status': 'ready', 'expression': 'a', 'answer': 1900, 'output_unit': 'money',
                             'operands': {'a': {'fact_id': 'table_1', 'source_token': '1900', 'unit': 'money'}}})
        with patch('evidence_lab.numeric.retrieve', return_value=({}, [only_header], ['q'], [])):
            result = run_numeric(q, index, complete, Budget())
        self.assertEqual(result['answer'], 1900)
        self.assertEqual(result['repair_rounds'], 1)

    def test_shared_runner_repairs_and_resume_spends_nothing(self):
        data, _ = self.numeric_data()
        seen = []
        def transport(cfg, payload):
            request = json.loads(payload['messages'][1]['content']); seen.append(request)
            if not request['repair_feedback']:
                return response({'status': 'insufficient', 'missing_queries': ['purchase price developed technology']})
            return response({'status': 'ready', 'answer': 999, 'expression': 'a/b', 'output_unit': 'ratio',
                             'operands': {'a': {'fact_id': 'table_1', 'source_token': '1900', 'unit': 'money'},
                                          'b': {'fact_id': 'table_2', 'source_token': '31300', 'unit': 'money'}}})
        with patch('evidence_lab.client.request', side_effect=transport) as call:
            out = self.path / 'run'
            summary = run(data, out, config=AgentConfig(judge_mode='openai_compatible'), api_config=self.api(), numeric=NumericConfig(top_k=1))
            self.assertEqual(summary['failures'], [])
            self.assertEqual(call.call_count, 2)
            self.assertEqual(summary['repair_rounds'], 1)
            self.assertAlmostEqual(read_jsonl(out / 'questions.jsonl')[0]['answer'], 1900/31300)
            run(data, out, config=AgentConfig(judge_mode='openai_compatible'), api_config=self.api(), numeric=NumericConfig(top_k=1))
            self.assertEqual(call.call_count, 2)
        self.assertTrue(seen[1]['repair_feedback'])
        self.assertNotIn('test-secret-key', (out / 'run_manifest.json').read_text())

    def test_no_repair_arm_stops_and_invalid_plan_is_not_published(self):
        data, _ = self.numeric_data()
        with patch('evidence_lab.client.request', return_value=response({'status': 'insufficient'})) as call:
            summary = run(data, self.path / 'run', config=AgentConfig(judge_mode='openai_compatible'),
                          api_config=self.api(), numeric=NumericConfig(max_repair_rounds=0))
            self.assertEqual(call.call_count, 1)
            self.assertEqual(summary['status'], {'needs_review': 1})

    def test_numeric_offline_never_reads_key_or_calls(self):
        data, _ = self.numeric_data()
        with patch('evidence_lab.client.request') as call:
            summary = run(data, self.path / 'offline', api_config=self.path / 'missing.env')
            self.assertEqual(summary['status'], {'needs_model_judge': 1})
            call.assert_not_called()

    def test_unknown_outcome_and_request_cap_do_not_rebill(self):
        client = CachedCompletion({'API_MODEL': 'fixture'}, self.path / 'requests.sqlite', 'run', max_requests=1)
        with patch('evidence_lab.client.request', side_effect=RuntimeError('interrupted')) as call:
            with self.assertRaises(RuntimeError): client([{'content': 'first'}], 10)
            with self.assertRaises(RuntimeError): client([{'content': 'first'}], 10)
            with self.assertRaisesRegex(RuntimeError, 'cap'): client([{'content': 'different'}], 10)
            self.assertEqual(call.call_count, 1)
        client.close()

    def test_whole_unit_budget_never_truncates_table(self):
        q = Question('q', '', '', 'revenue', {}, 'numeric')
        rows, packed = pack_numeric(q, [candidate('x', 'd', 'raw table ' * 10000)], Budget(), [])
        self.assertEqual(rows, [])
        self.assertEqual(packed['omitted_facts'], ['x'])
        with self.assertRaises(ValueError): pack_numeric(q, [], Budget(max_prompt_chars=10), [])

    def test_mcq_unknown_really_invokes_repair_and_accumulates_usage(self):
        def judgement(question, evidence):
            count[0] += 1
            unknown = count[0] == 1
            return JudgeOutput(mode='openai_compatible', confidence='test', status='model_judged', answer_raw='' if unknown else 'A',
                               total_tokens=15, option_judgement={label: {
                                   'verdict': 'UNKNOWN' if unknown else ('TRUE' if label == 'A' else 'FALSE'),
                                   'evidence_ids': [] if unknown else [evidence[0]['evidence_id']]}
                                   for label in question.options})
        count = [0]
        with patch('evidence_lab.runner.make_judge') as make:
            make.return_value.judge.side_effect = judgement
            summary = run(DATA, self.path / 'mcq', config=AgentConfig(judge_mode='openai_compatible',
                          llm_model='mock', llm_base_url='https://mock.invalid/v1'), limit=1)
        self.assertEqual(count[0], 2)
        self.assertEqual(summary['total_tokens'], 30)
        self.assertEqual(summary['status'], {'validated_structure': 1})

    def test_experiment_calls_production_runner_and_scores_after_predictions(self):
        raw = []
        old = []
        for cohort in ('old', 'new'):
            for kind, facts in [('text', ['text_0']), ('table', ['table_1']), ('mixed', ['text_0', 'table_1'])]:
                qid = cohort + '/' + kind
                raw.append({'id': qid, 'pre_text': ['Revenue 10'], 'post_text': [],
                            'table': [['', '2020'], ['Revenue', '10']],
                            'qa': {'question': 'Revenue for ' + qid, 'exe_ans': 10, 'gold_inds': dict.fromkeys(facts, 'SECRET')}})
                if cohort == 'old': old.append({'qid': qid})
        source, labels = self.path / 'source.json', self.path / 'old.jsonl'
        source.write_text(json.dumps(raw)); write_jsonl(labels, old)
        prepared = self.path / 'prepared'; prepare(source, labels, prepared, 1)
        def transport(cfg, payload):
            content = payload['messages'][1]['content']
            self.assertNotIn('SECRET', content)
            self.assertNotIn('expected', content)
            return response({'status': 'ready', 'answer': 10, 'expression': 'a', 'output_unit': 'money',
                             'operands': {'a': {'fact_id': 'text_0', 'source_token': '10', 'unit': 'money'}}})
        with patch('evidence_lab.client.request', side_effect=transport):
            metrics = experiment_run(prepared, self.path / 'out', self.api())
        self.assertEqual(len(metrics), 4)
        self.assertTrue(all(m['correct'] == 3 for m in metrics))
