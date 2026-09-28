from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

from agent.schema import Question, Candidate, ScoredEvidence, JudgeOutput, AgentConfig
from agent.io_utils import read_jsonl
from agent.model_client import ChatResponse, ChatUsage
from evidence_lab.audit import validate
from evidence_lab.benchmark import baseline, signature
from evidence_lab.budget import Budget, pack, prompt_chars
from evidence_lab.checkpoint import Checkpoints
from evidence_lab.data import adapt
from evidence_lab.retrieval import CachedIndex, retrieve
from evidence_lab.runner import run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'examples/lab'


def candidate(cid, doc, text, score=1.0, label=None):
    c = Candidate.from_selector_row({'candidate_id': cid, 'doc_id': doc, 'page_id': 1, 'text': text, 'unit_type': 'text'})
    return ScoredEvidence(c, score, {}, label)


class TemporaryTest(unittest.TestCase):
    def setUp(self):
        root = ROOT / '.test-tmp'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.path = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)


class RetrievalTests(unittest.TestCase):
    def test_exact_upstream_scores_features_and_ranks_twice(self):
        index = CachedIndex.from_paths(DATA / 'selector.jsonl', DATA / 'docs.jsonl')
        for q in map(Question.from_row, read_jsonl(DATA / 'questions.jsonl')):
            for _ in range(2):
                self.assertEqual(signature(baseline(index, q)), signature(retrieve(index, q)))

    def test_duplicate_candidate_id_rejected(self):
        c = candidate('same', 'one', '内容').candidate
        with self.assertRaises(ValueError):
            CachedIndex({'one': [c, c]}, {})

    def test_unknown_document_reports_missing(self):
        index = CachedIndex({}, {})
        q = Question('q', '', '', '问题', {'A': '一'}, 'mcq', doc_ids=['missing'])
        self.assertEqual(retrieve(index, q)[3], ['missing'])


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.q = Question('q', '', '', '比较甲乙收入', {'A':'甲收入', 'B':'乙收入'}, 'multi', doc_ids=['甲', '乙'])

    def test_global_budget_counts_question_and_metadata(self):
        items = {'A': [candidate('1','甲','甲收入10万元。'*200, 100, 'A')],
                 'B': [candidate('2','乙','乙收入20万元。'*200, 5, 'B')]}
        b = Budget(prompt_chars(self.q, []) + 1400, 18, 900)
        rows, info = pack(self.q, items, [], b)
        self.assertLessEqual(prompt_chars(self.q, rows), b.max_prompt_chars)
        self.assertEqual(info['prompt_chars'], prompt_chars(self.q, rows))
        self.assertTrue(info['missing_documents'])

    def test_cover_low_score_document_if_fits(self):
        rows, info = pack(self.q, {'A':[candidate('1','甲','甲收入10万元',100,'A')],
                                  'B':[candidate('2','乙','乙收入20万元',1,'B')]}, [], Budget())
        self.assertEqual(info['missing_documents'], [])
        self.assertEqual(info['missing_option_routes'], [])
        self.assertTrue(all(not r['support_options'] for r in rows))

    def test_duplicate_id_deduplicated_provenance_preserved(self):
        item = candidate('1', '甲', '甲收入10万元', 10, 'A')
        rows, _ = pack(self.q, {'A':[item], 'B':[item]}, [item])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['retrieval_options'], ['A', 'B'])

    def test_impossible_budget_fails_before_model_call(self):
        with self.assertRaises(ValueError):
            pack(self.q, {}, [], Budget(1))

    def test_zero_limits_rejected(self):
        with self.assertRaises(ValueError):
            Budget(max_evidence=0)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.q = Question('q', '', '', '收入', {'A':'甲'}, 'mcq', doc_ids=['甲'])
        self.rows, _ = pack(self.q, {'A':[candidate('1','甲','甲收入10万元',10,'A')]}, [])

    def judge(self, refs, verdict='TRUE', answer='A'):
        return JudgeOutput('mock', answer, {'A':{'verdict':verdict,'evidence_ids':refs}}, 'high', 'model_judged')

    def test_hallucinated_citation_rejected(self):
        self.assertIn('invalid_citation:A', validate(self.q, self.rows, self.judge([999]))[2])

    def test_contradictory_answer_rejected(self):
        self.assertIn('answer_verdict_mismatch', validate(self.q, self.rows, self.judge([1], 'FALSE'))[2])

    def test_tampered_quote_rejected(self):
        self.rows[0]['text'] = '伪造'
        self.assertIn('quote_hash_mismatch', validate(self.q, self.rows, self.judge([1]))[2])

    def test_structural_validation_not_semantic_proof(self):
        self.assertEqual(validate(self.q, self.rows, self.judge([1]))[1], 'validated_structure')

    def test_unknown_verdict_needs_review(self):
        self.assertEqual(validate(self.q, self.rows, self.judge([], 'UNKNOWN', ''))[1], 'needs_review')


class ResumeTests(TemporaryTest):
    def test_checkpoint_isolated_by_fingerprint(self):
        path = self.path / 'state.sqlite'
        a = Checkpoints(path, 'a')
        a.put('q', {'answer':'A'})
        a.close()
        b = Checkpoints(path, 'b')
        self.assertIsNone(b.get('q'))
        b.close()

    def test_partial_resume_skips_completed_questions(self):
        first = run(DATA, self.path / 'run', limit=1)
        self.assertEqual(first['completed'], 1)
        second = run(DATA, self.path / 'run')
        self.assertEqual((second['completed'], second['reused']), (2, 1))
        with patch('evidence_lab.runner.make_judge', side_effect=AssertionError('must not create judge')):
            third = run(DATA, self.path / 'run')
        self.assertEqual(third['reused'], 2)
        self.assertEqual(third['status'], {'needs_model_judge':2})

    def test_changed_config_cannot_reuse_output(self):
        run(DATA, self.path / 'run')
        with self.assertRaises(ValueError):
            run(DATA, self.path / 'run', Budget(max_prompt_chars=13000))

    def test_model_failure_not_checkpointed(self):
        with patch('evidence_lab.runner.make_judge', side_effect=RuntimeError('failure')):
            result = run(DATA, self.path / 'run')
        self.assertEqual(len(result['failures']), 2)
        retry = run(DATA, self.path / 'run')
        self.assertEqual((retry['reused'], retry['completed']), (0, 2))

    def test_prior_answers_not_allowed(self):
        with self.assertRaises(ValueError):
            run(DATA, self.path / 'run', config=AgentConfig(judge_mode='prior_csv'))

    def test_model_adapter_prompt_usage_and_audit_integrated(self):
        # Exercises the actual upstream JSON parsing/judge adapter; only transport
        # is stubbed, and this is not a model-quality or network integration test.
        payload = {'answer':'ABC', 'confidence':'high', 'option_judgement': {
            label:{'verdict':'TRUE' if label in 'ABC' else 'FALSE', 'evidence_ids':[1], 'reason':'fixture'}
            for label in 'ABCD'}}
        response = ChatResponse(json.dumps(payload), ChatUsage(100, 20, 120), 'test-model', {})
        config = AgentConfig(judge_mode='openai_compatible', llm_model='test-model',
                             llm_base_url='https://mock.invalid/v1', llm_api_key_env='LAB_TEST_API_KEY')
        with patch.dict(os.environ, {'LAB_TEST_API_KEY':'test-only'}), \
             patch('agent.model_client.OpenAICompatibleClient.chat', return_value=response) as transport:
            result = run(DATA, self.path / 'run', config=config, limit=1)
        self.assertEqual(result['status'], {'validated_structure':1})
        self.assertEqual(result['total_tokens'], 120)
        self.assertLessEqual(sum(len(m['content']) for m in transport.call_args.kwargs['messages']), 12000)

    def test_qwen_default_gate_blocks_before_transport(self):
        config = AgentConfig(judge_mode='qwen', llm_model='qwen-test', llm_base_url='https://mock.invalid/v1')
        with patch('agent.model_client.OpenAICompatibleClient.chat', side_effect=AssertionError('no call')) as transport:
            result = run(DATA, self.path / 'run', config=config, limit=1)
        self.assertEqual(result['completed'], 0)
        self.assertFalse(transport.called)


class AdapterTests(TemporaryTest):
    def test_label_exclusion_page_boundaries_and_hashes(self):
        source = self.path / 'source'
        source.mkdir()
        docs = [{'doc_id':'x','domain':'financial_reports','title':'测试',
                 'text':'[PDF_PAGE_1]第一页面收入10万元[PDF_PAGE_2]第二页面净利润2万元'}]
        qs = [{'qid':'q','doc_ids':['x'],'question':'收入','options':{'A':'10'},'answer':'A','gold':'A','pseudo_answer':'A'}]
        (source / 'documents.json').write_text(json.dumps(docs))
        (source / 'questions-a.json').write_text(json.dumps(qs))
        manifest = adapt(source, self.path / 'out', 100, 10)
        got = read_jsonl(self.path / 'out/questions.jsonl')[0]
        self.assertFalse({'answer','gold','pseudo_answer'} & got.keys())
        units = read_jsonl(self.path / 'out/selector.jsonl')
        self.assertEqual([u['page_id'] for u in units], [1,2])
        self.assertFalse(manifest['answers_imported'])
        self.assertTrue(all(u['locator']['quote_sha256'] for u in units))


if __name__ == '__main__':
    unittest.main()
