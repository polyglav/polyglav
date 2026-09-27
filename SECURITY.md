# Security

Polyglav has a deliberately small surface: zero dependencies core of Python standard library.

## Reporting vulnerabilities

Please report security issues privately instead of opening a public issue.

Contact: open an issue on GitHub with the `security` label, or reach out directly to the maintainer (see the GitHub profile at https://github.com/polyglav/polyglav).

## What to include

- Affected version
- Steps to reproduce
- Impact description
- Suggested fix, if any

## Scope

Tool execution (`run_command`) runs with the permissions of the launching user. Read/write/list outside the project worktree escalate to `ask`. `run_command` is `ask` by default. Do not run Polyglav as root or with an API server exposed without authentication.

## Plugins

Plugins are arbitrary Python code from the plugin roots (bundled `polyglav.plugins.bundled`, `~/.config/polyglav/plugins/`, `.polyglav/plugins/`) and run with the permissions of the launching user. Only install plugins you trust, and review a plugin's source before installing it. The core itself stays zero-dependency, and plugin third-party packages are only imported when their tools are actually called.
