import json
from unittest.mock import patch

from evidence_lab.api_config import read_config
from evidence_lab.experiments import prepare_finqa
from evidence_lab.model_experiment import answer_match, normalized, prepare, run, messages
from test_lab import TemporaryTest


class ModelExperimentTests(TemporaryTest):
    def config(self):
        p = self.path / 'config.env'
        p.write_text('API_BASE_URL="https://chat.ecnu.edu.cn/open/api/v1"\n'
                     'API_KEY="dummy-local-fixture"\nAPI_MODEL="ecnu-plus"\n')
        return p

    def test_config_is_data_not_shell(self):
        p = self.config()
        p.write_text(p.read_text().replace('dummy-local-fixture', '$(touch NEVER_EXECUTE)'))
        self.assertEqual(read_config(p)['API_KEY'], '$(touch NEVER_EXECUTE)')
        self.assertFalse((self.path / 'NEVER_EXECUTE').exists())

    def test_missing_config_and_embedded_credentials_rejected(self):
        p = self.config()
        p.write_text(p.read_text().replace('dummy-local-fixture', ''))
        with self.assertRaisesRegex(ValueError, 'API_KEY'):
            read_config(p)
        p = self.config()
        p.write_text(p.read_text().replace('https://chat.', 'https://secret@chat.'))
        with self.assertRaises(ValueError):
            read_config(p)

    def test_numeric_rounding_percent_and_no_scale_guess(self):
        self.assertTrue(answer_match('14.464%', .14464))
        self.assertTrue(answer_match('1,200', 1200))
        self.assertTrue(answer_match(.144642857, .14464))
        self.assertFalse(answer_match(14.464, .14464))
        self.assertFalse(answer_match(None, 0))
        self.assertFalse(answer_match(float('nan'), 0))
        self.assertTrue(answer_match('YES', 'yes'))
        self.assertFalse(answer_match(True, 'yes'))

    def fixtures(self):
        raw = []
        for kind, facts in [('text', ['text_0']), ('table', ['table_1']), ('mixed', ['text_0','table_1'])]:
            raw.append({'id': kind+'/2020/page_1.pdf-1', 'pre_text':['Revenue is 10.'],
                        'post_text':[], 'table':[['','2020'],['Revenue','10']],
                        'qa':{'question': 'What is revenue for '+kind+'?', 'exe_ans':10,
                              'gold_inds':{f:'LABEL_DO_NOT_SEND' for f in facts}}})
        source = self.path/'source.json'
        source.write_text(json.dumps(raw))
        data = self.path/'adapted'
        prepare_finqa(source, data)
        predictions = self.path/'retrieval.jsonl'
        rows = [{'qid': r['id'], 'variant': v, 'predicted_facts': list(r['qa']['gold_inds'])}
                for r in raw for v in ('full','token_only')]
        predictions.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        return data, source, predictions

    def test_prepare_separates_answers_and_inference(self):
        data, source, predictions = self.fixtures()
        out = self.path/'prepared'
        p = prepare(data, source, predictions, out, per_type=1)
        jobs = (out/'jobs.jsonl').read_text()
        self.assertNotIn('expected',jobs)
        self.assertNotIn('LABEL_DO_NOT_SEND',jobs)
        self.assertEqual(p['questions'],3)
        self.assertEqual(p['max_requests'],12)
        self.assertNotIn('oracle', json.dumps(messages('q', [])))

    def test_identical_prompts_reused_and_resume_no_calls(self):
        data, source, predictions = self.fixtures()
        prepared = self.path/'prepared'
        prepare(data, source, predictions, prepared, per_type=1)
        out = self.path/'run'
        def fake(cfg, payload):
            evidence = json.loads(payload['messages'][1]['content'])['evidence']
            refs = [r['fact_id'] for r in evidence]
            return {'status':'ok','content':json.dumps({'answer':10 if refs else None, 'evidence_ids':refs}),
                    'served_model':'fixture-model','finish_reason':'stop','latency_seconds':.01,
                    'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}
        with patch('evidence_lab.model_experiment.request',side_effect=fake) as call:
            first = run(prepared,out,self.config())
            self.assertEqual(call.call_count,6)
            again = run(prepared,out,self.config())
            self.assertEqual(call.call_count,6)
        self.assertEqual(first['physical_requests_total'],6)
        self.assertEqual(first['usage_reported']['total_tokens'],90)
        self.assertEqual(again['new_requests_this_invocation'],0)
        self.assertEqual(first['variants']['full']['correct'],3)
        self.assertEqual(first['variants']['no_retrieval']['correct'],0)
        self.assertNotIn('dummy-local-fixture',(out/'run_manifest.json').read_text())

    def test_changed_prepared_input_rejected_before_transport(self):
        data, source, predictions = self.fixtures()
        prepared = self.path/'prepared'
        prepare(data,source,predictions,prepared,per_type=1)
        with (prepared/'jobs.jsonl').open('a') as f:
            f.write('{}\n')
        with patch('evidence_lab.model_experiment.request') as call:
            with self.assertRaisesRegex(ValueError,'changed'):
                run(prepared,self.path/'out',self.config())
            call.assert_not_called()
