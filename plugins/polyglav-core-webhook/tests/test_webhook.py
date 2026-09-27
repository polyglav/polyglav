import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import plugin


def _config(webhook: str):
    config = MagicMock()
    config.get.return_value = webhook
    return config


class _Resp:
    def __init__(self, content: bytes = b'ok'):
        self._content = content

    def read(self):
        return self._content


class TestWebhookService(unittest.TestCase):

    def test_no_op_without_url(self):
        with patch('plugin.request.urlopen') as urlopen:
            plugin.SERVICE.report({'status': 'verified'}, _config(''))
        urlopen.assert_not_called()

    def test_posts_payload_on_url(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured['url'] = req.full_url
            captured['method'] = req.get_method()
            captured['body'] = json.loads(req.data)
            captured['content_type'] = req.get_header('Content-type')
            captured['timeout'] = timeout
            return _Resp()

        payload = {'event': 'job.run.completed', 'job': 'nightly',
                   'status': 'failed', 'session': 'job_123'}
        with patch('plugin.request.urlopen', side_effect=fake_urlopen):
            plugin.SERVICE.report(payload, _config('https://hooks.example/x'))
        self.assertEqual(captured['url'], 'https://hooks.example/x')
        self.assertEqual(captured['method'], 'POST')
        self.assertEqual(captured['content_type'], 'application/json')
        self.assertEqual(captured['timeout'], plugin.TIMEOUT)
        self.assertEqual(captured['body'], payload)

    def test_failure_is_tolerated(self):
        with patch('plugin.request.urlopen', side_effect=Exception('boom')):
            with patch('sys.stderr') as stderr:
                plugin.SERVICE.report({'status': 'verified'},
                                      _config('https://hooks.example/x'))
        stderr.write.assert_called_once()
        self.assertIn('failed', stderr.write.call_args[0][0])


if __name__ == '__main__':
    unittest.main()