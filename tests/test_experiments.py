import copy
import json
import unittest

from agent.schema import Question
from evidence_lab.budget import Budget, pack, prompt_chars
from evidence_lab.experiments import (finqa_inputs, prepare_finqa, retrieval_metrics,
                                      paired_cluster_interval, table_row_text)
from evidence_lab.retrieval import retrieve, CachedIndex
from test_lab import TemporaryTest, candidate, DATA


class ExperimentsTests(TemporaryTest):
    def fixture(self):
        return {'id': 'ACME/2020/page_1.pdf-1', 'pre_text': ['Revenue was 12.'],
                'post_text': ['Expenses were 5.'],
                'table': [['', '2020', '2019'], ['Revenue', '12', '10']],
                'qa': {'question': 'What was revenue in 2020?', 'gold_inds': {'table_1': 'SECRET'},
                       'exe_ans': 'SECRET', 'program': 'SECRET'}, 'model_input': 'SECRET'}

    def test_gold_mutation_cannot_change_inference(self):
        row = self.fixture()
        expected = finqa_inputs(row)
        changed = copy.deepcopy(row)
        changed['qa'].update(gold_inds={'text_1': 'OTHER'}, exe_ans='OTHER', program='OTHER')
        changed['model_input'] = 'OTHER'
        self.assertEqual(expected, finqa_inputs(changed))
        self.assertNotIn('SECRET', json.dumps(expected))

    def test_corrected_table_template_and_fact_numbering(self):
        self.assertEqual(table_row_text(['', '2020', '2019'], ['Revenue', '12', '10']),
                         'the Revenue of 2020 is 12 ; the Revenue of 2019 is 10 ;')
        _, _, units = finqa_inputs(self.fixture())
        self.assertEqual([u['locator']['fact_id'] for u in units], ['text_0', 'text_1', 'table_0', 'table_1'])

    def test_unmapped_or_empty_gold_rejected(self):
        for gold in ({}, {'table_99': 'bad'}):
            row = self.fixture()
            row['qa']['gold_inds'] = gold
            source = self.path / 'source.json'
            source.write_text(json.dumps([row]))
            with self.assertRaises(ValueError):
                prepare_finqa(source, self.path / 'out')

    def test_adapter_isolates_gold_and_rejects_overwrite(self):
        source = self.path / 'source.json'
        source.write_text(json.dumps([self.fixture()]))
        out = self.path / 'out'
        manifest = prepare_finqa(source, out)
        self.assertEqual(manifest['questions'], 1)
        for path in out.glob('*.jsonl'):
            self.assertNotIn('SECRET', path.read_text())
        with self.assertRaises(FileExistsError):
            prepare_finqa(source, out)

    def test_recall_denominator_is_gold_not_returned_count(self):
        metrics = retrieval_metrics(['text_1', 'text_1', 'wrong', 'text_2'], ['text_1', 'text_2'])
        self.assertEqual(metrics, {'recall_at_3': .5, 'all_at_3': 0, 'recall_at_5': 1, 'all_at_5': 1})
        with self.assertRaises(ValueError):
            retrieval_metrics([], [])

    def test_paired_bootstrap_uses_question_pairs_and_company_clusters(self):
        rows = [{'qid': q, 'company': company, 'variant': variant, 'all_at_5': value}
                for q, company in [('one', 'A'), ('two', 'A'), ('three', 'B')]
                for variant, value in [('full', 1), ('ablated', 0)]]
        result = paired_cluster_interval(rows, 'ablated', 'all_at_5', repeats=100)
        self.assertEqual(result['difference'], -1)
        self.assertEqual(result['ci95'], [-1, -1])
        self.assertEqual(result['clusters'], 2)

    def test_disabled_priority_still_measures_original_goals(self):
        q = Question('q', '', '', 'compare', {'A': 'one', 'B': 'two'}, 'multi', doc_ids=['one', 'two'])
        opts = {'A': [candidate('high', 'one', 'one revenue', 100, 'A')],
                'B': [candidate('low', 'two', 'two revenue', 1, 'B')]}
        budget = Budget(max_evidence=1)
        selected, info = pack(q, opts, [], budget, prioritize_docs=False, prioritize_options=False)
        self.assertEqual(selected[0]['doc_id'], 'one')
        self.assertEqual(info['missing_documents'], ['two'])
        self.assertEqual(info['missing_option_routes'], ['B'])
        self.assertLessEqual(prompt_chars(q, selected), budget.max_prompt_chars)

    def test_no_option_queries_and_numeric_ablation(self):
        row = self.fixture()
        q, doc, units = finqa_inputs(row)
        from agent.schema import Candidate
        cs = [Candidate.from_selector_row(u) for u in units]
        index = CachedIndex({q['qid']: cs}, {q['qid']: doc})
        question = Question.from_row(q)
        question.options = {'A': '12', 'B': '99'}
        opts, _, _, _ = retrieve(index, question, include_options=False)
        self.assertEqual(opts, {})
        full = {r.candidate.candidate_id: r for r in retrieve(index, question)[1]}
        reduced = {r.candidate.candidate_id: r for r in retrieve(index, question, scoring='no_numeric_bonus')[1]}
        for cid, r in reduced.items():
            before = full[cid]
            expected = before.features['number_score'] + before.features['year_score']
            self.assertAlmostEqual(before.score - r.score, expected)
        with self.assertRaises(ValueError):
            retrieve(index, question, scoring='unknown')


if __name__ == '__main__':
    unittest.main()
