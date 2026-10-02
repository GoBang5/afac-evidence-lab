"""MCQ adapter for the same local-config transport used by numeric QA."""
from agent.judge import ModelJudge
from agent.model_client import ChatResponse, ChatUsage


class LocalJudge(ModelJudge):
    def __init__(self, complete, config):
        self.mode, self.config = config.judge_mode, config
        self.complete, self.client = complete, self

    def chat(self, messages, temperature, max_tokens):
        if temperature != 0:
            raise ValueError('Local workflow currently requires temperature=0')
        result = self.complete(messages, max_tokens)
        if result.get('finish_reason') != 'stop':
            raise RuntimeError('Incomplete model response')
        usage = result.get('usage') or {}
        return ChatResponse(result['content'], ChatUsage(**{k: usage.get(k) or 0 for k in
                            ('prompt_tokens', 'completion_tokens', 'total_tokens')}), result.get('served_model', ''), {})
