import unittest

from polyglav.engine import Engine
from polyglav.providers.base import BaseProvider, OpenAICompatibleProvider
from polyglav.sessions.manager import Session


class TestProviderSessionBinding(unittest.TestCase):

    def test_base_provider_stores_session_id(self):
        p = BaseProvider(session_id='abc123')
        self.assertEqual(p.session_id, 'abc123')

    def test_openai_compatible_provider_stores_session_id(self):
        p = OpenAICompatibleProvider(base_url='https://x.test',
                                     session_id='ses_1')
        self.assertEqual(p.session_id, 'ses_1')

    def test_default_session_id_is_empty(self):
        self.assertEqual(BaseProvider().session_id, '')

    def _engine(self, owns, session_id):
        engine = Engine.__new__(Engine)
        engine.provider = BaseProvider(session_id='original')
        engine._owns_provider = owns
        engine.current_session = Session('ses_x', session_id=session_id)
        return engine

    def test_bind_sets_owned_provider_session(self):
        engine = self._engine(True, 'abcdef')
        engine._bind_provider_session()
        self.assertEqual(engine.provider.session_id, 'abcdef')

    def test_bind_preserves_shared_provider_session(self):
        engine = self._engine(False, 'abcdef')
        engine._bind_provider_session()
        self.assertEqual(engine.provider.session_id, 'original')

    def test_bind_skips_provider_without_session_id(self):
        engine = Engine.__new__(Engine)
        engine.provider = object()
        engine._owns_provider = True
        engine.current_session = Session('ses_x', session_id='abcdef')
        engine._bind_provider_session()

    def test_current_session_id_helper(self):
        engine = self._engine(True, 'abcdef')
        self.assertEqual(engine._current_session_id(), 'abcdef')
        bare = Engine.__new__(Engine)
        self.assertEqual(bare._current_session_id(), '')


if __name__ == '__main__':
    unittest.main()
