from polyglav.providers.base import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    DEFAULT_BASE_URL = 'https://api.groq.com/openai/v1'
    DEFAULT_MODEL = 'llama-3.3-70b-versatile'
    HOST_PATTERNS = ('groq.com',)


def register_providers(providers):
    providers['groq'] = GroqProvider