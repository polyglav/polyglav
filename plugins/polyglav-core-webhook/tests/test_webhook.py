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


def _config(webhook: str, secret: str = ''):
    config = MagicMock()
    values = {'report.webhook': webhook, 'report.webhook_secret': secret}
    config.get.side_effect = lambda key, default=None: values.get(key, default)
    return config


class _Resp:
    def __init__(self, content: bytes = b'ok'):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

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

    def test_refuses_plaintext_non_loopback(self):
        with patch('plugin.request.urlopen') as urlopen:
            with patch('sys.stderr') as stderr:
                plugin.SERVICE.report({'status': 'verified'},
                                      _config('http://hooks.example/x'))
        urlopen.assert_not_called()
        self.assertIn('https', stderr.write.call_args[0][0])

    def test_allows_plaintext_loopback(self):
        with patch('plugin.request.urlopen', return_value=_Resp()) as urlopen:
            plugin.SERVICE.report({'status': 'verified'},
                                  _config('http://127.0.0.1:9000/hook'))
        urlopen.assert_called_once()

    def test_signature_header(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured['signature'] = req.get_header('X-polyglav-signature')
            captured['timestamp'] = req.get_header('X-polyglav-timestamp')
            captured['body'] = req.data.decode('utf-8')
            return _Resp()

        payload = {'event': 'job.run.completed', 'job': 'nightly'}
        with patch('plugin.request.urlopen', side_effect=fake_urlopen):
            plugin.SERVICE.report(payload, _config(
                'https://hooks.example/x', secret='topsecret'))
        self.assertTrue(captured['signature'].startswith('sha256='))
        expected = plugin._signature('topsecret', captured['timestamp'],
                                     captured['body'])
        self.assertEqual(captured['signature'], f'sha256={expected}')
        self.assertEqual(json.loads(captured['body']), payload)

    def test_no_signature_without_secret(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured['signature'] = req.get_header('X-polyglav-signature')
            return _Resp()

        with patch('plugin.request.urlopen', side_effect=fake_urlopen):
            plugin.SERVICE.report({'event': 'job.run.completed'},
                                  _config('https://hooks.example/x'))
        self.assertIsNone(captured['signature'])


if __name__ == '__main__':
    unittest.main()