import uuid

from polyglav import get_version
from polyglav.providers.base import OpenAICompatibleProvider


class OpenCodeProviderBase(OpenAICompatibleProvider):
    ECHO_REASONING = True

    def __init__(self, **kwargs):
        session_id = kwargs.pop('session_id', None) or uuid.uuid4().hex
        super().__init__(**kwargs)
        self.session_id = session_id

    def _headers(self):
        headers = super()._headers()
        headers['x-opencode-session'] = self.session_id
        headers['User-Agent'] = f'polyglav/{get_version()}'
        return headers