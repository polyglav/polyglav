import hashlib
import hmac
import json
import sys
import time
from urllib import parse, request

TIMEOUT = 10
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def _is_loopback(url: str) -> bool:
    try:
        host = (parse.urlparse(url).hostname or '').lower()
    except ValueError:
        return False
    return host in LOOPBACK_HOSTS


def _signature(secret: str, timestamp: str, body: str) -> str:
    signed = f'{timestamp}.{body}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()


class WebhookReportService:
    def report(self, payload: dict, config) -> None:
        url = (config.get('report.webhook') or '').strip()
        if not url:
            return
        secret = (config.get('report.webhook_secret') or '').strip()
        if url.lower().startswith('http://') and not _is_loopback(url):
            sys.stderr.write(
                f'[webhook] refusing plaintext report to {url}: use https\n')
            return
        body = json.dumps(payload)
        headers = {'Content-Type': 'application/json'}
        if secret:
            timestamp = str(int(time.time()))
            headers['X-Polyglav-Timestamp'] = timestamp
            headers['X-Polyglav-Signature'] = (
                f'sha256={_signature(secret, timestamp, body)}')
        req = request.Request(
            url, data=body.encode('utf-8'), method='POST', headers=headers)
        try:
            with request.urlopen(req, timeout=TIMEOUT) as resp:
                resp.read()
        except Exception as e:
            sys.stderr.write(f'[webhook] report to {url} failed: {e}\n')


SERVICE = WebhookReportService()


def register_services(services):
    services['report'] = SERVICE
