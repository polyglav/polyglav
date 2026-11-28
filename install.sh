#!/bin/sh
set -eu

say() {
    printf '%s\n' "$*"
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

PYTHON=
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            PYTHON=$candidate
            break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.11 or newer is required."

WINDOWS=0
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;;
esac

run_root() {
    if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        return 1
    fi
}

install_pip() {
    if "$PYTHON" -m pip --version >/dev/null 2>&1; then
        return 0
    fi
    say "pip is missing; trying ensurepip"
    "$PYTHON" -m ensurepip --upgrade >/dev/null 2>&1 || true
    if "$PYTHON" -m pip --version >/dev/null 2>&1; then
        return 0
    fi
    say "pip is missing; trying the system package manager"
    if command -v apt-get >/dev/null 2>&1; then
        run_root apt-get -qq update || return 1
        run_root env DEBIAN_FRONTEND=noninteractive apt-get -qq install -y python3-pip || return 1
    elif command -v dnf >/dev/null 2>&1; then
        run_root dnf -q install -y python3-pip || return 1
    elif command -v yum >/dev/null 2>&1; then
        run_root yum -q install -y python3-pip || return 1
    elif command -v apk >/dev/null 2>&1; then
        run_root apk add --no-cache -q py3-pip || return 1
    elif command -v pacman >/dev/null 2>&1; then
        run_root pacman -Sy --noconfirm -q python-pip || return 1
    elif command -v zypper >/dev/null 2>&1; then
        run_root zypper --quiet --non-interactive install python3-pip || return 1
    else
        return 1
    fi
    if "$PYTHON" -m pip --version >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

say "Installing polyglav"
say ""

if command -v uv >/dev/null 2>&1; then
    if [ "$WINDOWS" = "1" ]; then
        uv tool install --force --with pyreadline3 polyglav
    else
        uv tool install --force polyglav
    fi
elif command -v pipx >/dev/null 2>&1; then
    pipx install --force polyglav
    if [ "$WINDOWS" = "1" ]; then
        pipx inject polyglav pyreadline3
    fi
else
    install_pip || die "pip is required. Install python3-pip on Linux, or reinstall Python with pip."
    "$PYTHON" -m pip install --user --upgrade polyglav
    if [ "$WINDOWS" = "1" ]; then
        "$PYTHON" -m pip install --user --upgrade pyreadline3
    fi
fi

say ""
say "Installed. Start the REPL with:"
say ""
say "  polyglav"
say ""
say "If the command is not on PATH, run: $PYTHON -m polyglav"
say "Docs: https://polyglav.github.io/polyglav/"
