from polyglav.providers.base import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    DEFAULT_BASE_URL = 'https://api.ollama.com'
    DEFAULT_MODEL = 'llama3.2'
    HOST_PATTERNS = ('ollama.com', 'ollama.ai')

    def _reasoning_payload(self, payload: dict) -> dict:
        if self._reasoning_off(self.reasoning):
            payload['enable_thinking'] = False
            return payload
        payload['enable_thinking'] = True
        if isinstance(self.reasoning, str) and self.reasoning in ('low', 'medium', 'high'):
            payload['chat_template_kwargs'] = {'thinking': True}
        return payload


def register_providers(providers):
    providers['ollama'] = OllamaProvider