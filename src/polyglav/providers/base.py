import json
import urllib.request
import urllib.error

from ..utils.http import stream_sse, PostRedirectHandler

USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


class BaseProvider:
    def __init__(self, base_url: str = '', api_key: str = '',
                 model: str = '', temperature: float = 0.7,
                 max_tokens: int = 0, reasoning=None, session_id: str = ''):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning = reasoning
        self.session_id = session_id

    def chat(self, messages: list[dict], stream: bool = True,
             tools: list[dict] | None = None):
        raise NotImplementedError

    def chat_nonstreaming(self, messages: list[dict],
                          tools: list[dict] | None = None) -> dict:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        raise NotImplementedError

    def check_connection(self) -> tuple[bool, str]:
        raise NotImplementedError


class OpenAICompatibleProvider(BaseProvider):
    DEFAULT_BASE_URL = ''
    DEFAULT_MODEL = ''
    HOST_PATTERNS: tuple[str, ...] = ()
    ECHO_REASONING = False

    def __init__(self, **kwargs):
        if not kwargs.get('base_url'):
            kwargs['base_url'] = self.DEFAULT_BASE_URL
        if not kwargs.get('model'):
            kwargs['model'] = self.DEFAULT_MODEL
        super().__init__(**kwargs)

    def _headers(self):
        headers = {'Content-Type': 'application/json',
                   'User-Agent': USER_AGENT}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    @staticmethod
    def _reasoning_off(reasoning) -> bool:
        return reasoning in (False, None, 'off', 'none', 'false', 0, '0')

    def _reasoning_payload(self, payload: dict) -> dict:
        if self._reasoning_off(self.reasoning):
            return payload
        if isinstance(self.reasoning, str) and self.reasoning in ('low', 'medium', 'high'):
            payload['reasoning_effort'] = self.reasoning
        return payload

    def _prepare_messages(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for message in messages:
            prepared = dict(message)
            thinking = prepared.pop('thinking', None)
            if (self.ECHO_REASONING and thinking
                    and prepared.get('role') == 'assistant'):
                prepared['reasoning_content'] = thinking
            out.append(prepared)
        return out

    def _payload(self, messages, stream=False, tools=None):
        payload = {
            'model': self.model,
            'messages': self._prepare_messages(messages),
            'temperature': self.temperature,
            'stream': stream,
        }
        if self.max_tokens > 0:
            payload['max_tokens'] = self.max_tokens
        if tools:
            payload['tools'] = tools
        self._reasoning_payload(payload)
        return payload

    def _post(self, payload):
        url = self._endpoint()
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=self._headers())
        try:
            opener = urllib.request.build_opener(PostRedirectHandler)
            with opener.open(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            return {'error': {'code': e.code, 'message': body}}
        except urllib.error.URLError as e:
            return {'error': {'code': 0, 'message': f'Network error: {e.reason}'}}
        except Exception as e:
            return {'error': {'code': 0, 'message': str(e)}}

    def chat_nonstreaming(self, messages: list[dict],
                          tools: list[dict] | None = None) -> dict:
        payload = self._payload(messages, stream=False, tools=tools)
        result = self._post(payload)
        if 'error' in result:
            return result
        choices = result.get('choices') or []
        if not choices:
            return {'error': {'code': 0, 'message': 'No choices in response'}}
        choice = choices[0] or {}
        message = choice.get('message') or {}
        return {
            'role': message.get('role', 'assistant'),
            'content': message.get('content'),
            'tool_calls': message.get('tool_calls'),
            'finish_reason': choice.get('finish_reason'),
        }

    def chat(self, messages: list[dict], stream: bool = True,
             tools: list[dict] | None = None):
        payload = self._payload(messages, stream=stream, tools=tools)

        if not stream:
            result = self._post(payload)
            if 'error' in result:
                yield {'type': 'error', 'code': result['error']['code'], 'message': result['error']['message']}
                return
            choices = result.get('choices') or []
            if not choices:
                yield {'type': 'error', 'code': 0, 'message': 'No choices in response'}
                return
            content = (choices[0] or {}).get('message') or {}
            content = content.get('content')
            yield {'type': 'token', 'content': content}
            yield {'type': 'done'}
            return

        tool_calls_acc: dict[int, dict] = {}
        usage = None
        finished_reason = None
        saw_done = False
        for event in stream_sse(self._endpoint(), self._headers(), payload):
            if event.get('type') == 'error':
                yield event
                return
            if event.get('type') == 'done':
                saw_done = True
                break
            if event.get('usage'):
                usage = event.get('usage')
            choices = event.get('choices') or []
            if not choices:
                continue
            choice = choices[0] or {}
            delta = choice.get('delta') or {}
            reasoning = (delta.get('reasoning_content') or '') or (delta.get('reasoning') or '')
            if reasoning:
                yield {'type': 'thinking', 'content': reasoning}
                continue
            for tc in delta.get('tool_calls') or []:
                idx = tc.get('index', 0)
                entry = tool_calls_acc.setdefault(idx, {
                    'id': '', 'type': 'function',
                    'function': {'name': '', 'arguments': ''},
                })
                if tc.get('id'):
                    entry['id'] = tc['id']
                fn = tc.get('function') or {}
                if fn.get('name'):
                    entry['function']['name'] = fn['name']
                if fn.get('arguments'):
                    entry['function']['arguments'] += fn['arguments']
            content = delta.get('content') or ''
            if content:
                yield {'type': 'token', 'content': content}
            finish = choice.get('finish_reason')
            if finish:
                finished_reason = finish
        if tool_calls_acc:
            yield {'type': 'tool_calls', 'tool_calls': list(tool_calls_acc.values())}
        elif finished_reason:
            done = {'type': 'done', 'reason': finished_reason}
            if usage:
                done['usage'] = usage
            yield done
        elif saw_done:
            yield {'type': 'done'}

    def _endpoint(self):
        base = self.base_url.rstrip('/')
        if base.endswith('/v1'):
            return f'{base}/chat/completions'
        return f'{base}/v1/chat/completions'

    def list_models(self) -> list[str]:
        models, _ = self._fetch_models()
        return models

    def check_connection(self) -> tuple[bool, str]:
        models, error = self._fetch_models()
        if error:
            return False, error
        return True, _connection_message(models, self.model)

    def _fetch_models(self) -> tuple[list[str], str | None]:
        base = self.base_url.rstrip('/')
        url = f'{base}/v1/models' if not base.endswith('/v1') else f'{base}/models'
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace').strip()
            return [], f'HTTP {e.code}: {body or e.reason}'
        except urllib.error.URLError as e:
            return [], f'Network error: {e.reason}'
        except Exception as e:
            return [], str(e)
        return [m['id'] for m in data.get('data', []) if isinstance(m, dict) and 'id' in m], None


def _connection_message(models: list[str], model: str) -> str:
    if not models:
        return 'connected (no models listed)'
    note = ''
    if model and model not in models:
        note = f' (configured model "{model}" not in the model list)'
    return f'{len(models)} models available{note}'
