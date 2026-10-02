"""Secret-safe OpenAI-compatible transport and resumable request accounting."""
import json
import time
import urllib.error
import urllib.request
from .checkpoint import Checkpoints, fingerprint


class CachedCompletion:
    """One process per output directory. Unknown outcomes never auto-rebill."""
    def __init__(self, config, path, identity, max_requests=100, max_prompt_chars=12000):
        self.config = config
        self.store = Checkpoints(path, identity)
        self.max_requests = max_requests
        self.max_prompt_chars = max_prompt_chars
        self.new_calls = 0

    def __call__(self, messages, max_tokens):
        if sum(len(m['content']) for m in messages) > self.max_prompt_chars:
            raise ValueError('Prompt budget exceeded before transport')
        payload = {'model': self.config['API_MODEL'], 'messages': messages,
                   'temperature': 0, 'max_tokens': max_tokens,
                   'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}}
        key = fingerprint(payload)
        response = self.store.get(key)
        if response is None:
            count = self.store.conn.execute('SELECT COUNT(*) FROM results WHERE run_key=?', (self.store.key,)).fetchone()[0]
            if count >= self.max_requests:
                raise RuntimeError('Request cap reached')
            self.store.put(key, {'status': 'in_flight'})
            response = request(self.config, payload)
            self.store.put(key, response)
            self.new_calls += 1
        if response.get('status') != 'ok':
            raise RuntimeError('Request failed or outcome unknown; automatic rebilling disabled')
        return {**response, 'request_hash': key}

    def close(self):
        self.store.close()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(cfg, payload):
    req = urllib.request.Request(cfg['API_BASE_URL'].rstrip('/') + '/chat/completions',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + cfg['API_KEY']}, method='POST')
    started = time.perf_counter()
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=50) as resp:
            raw = json.load(resp)
        choice = raw['choices'][0]
        content = str(choice['message'].get('content') or '').replace(cfg['API_KEY'], '[REDACTED]')
        usage = raw.get('usage') or {}
        result = {'status': 'ok', 'content': content, 'finish_reason': choice.get('finish_reason'),
                  'served_model': str(raw.get('model') or '').replace(cfg['API_KEY'], '[REDACTED]'),
                  'usage': {k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}}
    except urllib.error.HTTPError as exc:
        result = {'status': 'http_error', 'http_status': exc.code}
    except Exception as exc:
        # Never log provider error bodies, request headers, or exception repr.
        result = {'status': 'error', 'error_type': type(exc).__name__}
    result['latency_seconds'] = time.perf_counter() - started
    return result
