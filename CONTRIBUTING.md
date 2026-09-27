# Contributing

Thanks for contributing to Polyglav.

## Getting started

```bash
git clone https://github.com/polyglav/polyglav.git && cd polyglav
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/polyglav
```

The project targets Python >=3.10 and uses only the standard library, with no external dependencies.

## Running tests

```bash
python -m unittest discover tests
```

Tests are mock-based: no network, no API key required. Run them before submitting changes.

## Project layout

See [AGENTS.md](AGENTS.md) for the architecture and conventions (agent loop, tool registry, command registry, config schema).

## Pull requests

- Keep changes focused, with one logical change per PR
- Type hints required on all function signatures
- No comments in code
- Add or update tests for the change
- Update `CHANGELOG.md` and `TODO.md` per the conventions in [AGENTS.md](AGENTS.md)
- Prefer `pathlib.Path`, stdlib only
