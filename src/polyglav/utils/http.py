import urllib.request
import urllib.error
import json


class PostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code in (301, 302, 303, 307, 308):
            return urllib.request.Request(
                newurl,
                data=req.data,
                headers=req.headers,
                method=req.get_method(),
                origin_req_host=req.origin_req_host,
                unverifiable=True,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(PostRedirectHandler)


def stream_sse(url, headers, payload, timeout=120):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')

    try:
        with _opener().open(req, timeout=timeout) as resp:
            buffer = b''
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith(b'data: '):
                        data_str = line[6:].decode('utf-8', errors='replace')
                        if data_str == '[DONE]':
                            yield {'type': 'done'}
                            return
                        try:
                            yield json.loads(data_str)
                        except json.JSONDecodeError:
                            pass
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        yield {'type': 'error', 'code': e.code, 'message': body}
    except Exception as e:
        yield {'type': 'error', 'message': str(e)}
