import json

SCHEME = 'polyglav://session/'


def resource_uri(name: str) -> str:
    return f'{SCHEME}{name}'


def list_resources(engine) -> list[dict]:
    return [
        {'uri': resource_uri(name), 'name': name, 'mimeType': 'application/json'}
        for name in engine.sessions.list()
    ]


def read_resource(engine, uri: str) -> dict | None:
    if not uri.startswith(SCHEME):
        return None
    name = uri[len(SCHEME):]
    if not name:
        return None
    session = engine.sessions.read(name)
    if session is None:
        return None
    return {
        'uri': uri,
        'name': name,
        'mimeType': 'application/json',
        'text': json.dumps(session.to_dict(), indent=2),
    }
