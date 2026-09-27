from opencode_base import OpenCodeProviderBase


class OpenCodeGoProvider(OpenCodeProviderBase):
    DEFAULT_BASE_URL = 'https://opencode.ai/zen/go/v1'
    DEFAULT_MODEL = 'deepseek-v4-flash'
    HOST_PATTERNS = ('opencode.ai/zen/go',)

    def _payload(self, messages, stream=False, tools=None):
        payload = super()._payload(messages, stream=stream, tools=tools)
        model = self.model
        if model.startswith('opencode-go/'):
            payload['model'] = model[len('opencode-go/'):]
        return payload