#!/bin/sh
set -eu

say() {
    printf '%s\n' "$*"
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.11 or newer."

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python 3.11 or newer is required."

say "Installing polyglav"
say ""

if command -v uv >/dev/null 2>&1; then
    uv tool install --force polyglav
elif command -v pipx >/dev/null 2>&1; then
    pipx install --force polyglav
else
    python3 -m pip install --user --upgrade polyglav
fi

say ""
say "Installed. Start the REPL with:"
say ""
say "  polyglav"
say ""
say "If the command is not on PATH, run: python3 -m polyglav"
say "Docs: https://polyglav.github.io/polyglav/"
