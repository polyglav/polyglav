import json
import sys
from urllib import request

TIMEOUT = 10


class WebhookReportService:
    def report(self, payload: dict, config) -> None:
        url = (config.get('report.webhook') or '').strip()
        if not url:
            return
        body = json.dumps(payload).encode('utf-8')
        req = request.Request(
            url, data=body, method='POST',
            headers={'Content-Type': 'application/json'})
        try:
            with request.urlopen(req, timeout=TIMEOUT) as resp:
                resp.read()
        except Exception as e:
            sys.stderr.write(f'[webhook] report to {url} failed: {e}\n')


SERVICE = WebhookReportService()


def register_services(services):
    services['report'] = SERVICE