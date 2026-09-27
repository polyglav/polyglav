from pathlib import Path


class ToolPolicy:
    def __init__(self, permissions: dict, allow: list | None = None,
                 deny: list | None = None, worktree: Path | None = None,
                 resolvers: dict | None = None, grants: list | None = None):
        self.permissions = dict(permissions or {})
        self.allow = set(allow or [])
        self.deny = set(deny or [])
        self.worktree = worktree.resolve() if worktree else None
        self.resolvers = dict(resolvers or {})
        self.grants = list(grants or [])

    def grant(self, name: str, permission_key: str, scope: str = 'once',
              origin: str = 'supervisor') -> dict:
        entry = {
            'name': name or '',
            'permission': permission_key,
            'scope': 'always' if scope == 'always' else 'once',
            'remaining': None if scope == 'always' else 1,
            'origin': origin,
        }
        self.grants.append(entry)
        return entry

    def grant_for(self, name: str, permission_key: str) -> dict | None:
        for entry in self.grants:
            if entry.get('permission') != permission_key:
                continue
            grant_name = entry.get('name') or ''
            if grant_name and grant_name != name:
                continue
            if entry.get('scope') == 'always' or entry.get('remaining', 0) > 0:
                return entry
        return None

    def has_grant(self, name: str, permission_key: str) -> bool:
        return self.grant_for(name, permission_key) is not None

    def consume(self, name: str, permission_key: str) -> dict | None:
        entry = self.grant_for(name, permission_key)
        if entry is None:
            return None
        if entry.get('scope') == 'always':
            return entry
        entry['remaining'] = entry.get('remaining', 1) - 1
        if entry['remaining'] <= 0:
            self.grants.remove(entry)
        return entry

    def _base_action(self, name: str, permission_key: str) -> str:
        if name in self.deny:
            return 'deny'
        if self.allow and name not in self.allow:
            return 'deny'
        action = self.permissions.get(permission_key, 'ask')
        return action if action in ('allow', 'ask', 'deny') else 'ask'

    def _outside_worktree(self, path: str) -> bool:
        if not self.worktree:
            return False
        try:
            p = Path(path).expanduser().resolve()
        except OSError:
            return True
        try:
            return not p.is_relative_to(self.worktree)
        except OSError:
            return True

    def action(self, name: str, permission_key: str,
               path: str | None = None, args: dict | None = None) -> str:
        if self.has_grant(name, permission_key):
            action = 'allow'
        else:
            action = self._base_action(name, permission_key)
        if action != 'deny' and args is not None:
            resolver = self.resolvers.get(name)
            if resolver is not None:
                try:
                    resolved = resolver(args)
                except Exception:
                    resolved = None
                if resolved in ('allow', 'ask', 'deny'):
                    action = resolved
        if action == 'allow' and path and self._outside_worktree(path):
            return 'ask'
        return action

    def allowed(self, name: str, permission_key: str | None = None) -> bool:
        if name in self.deny or (self.allow and name not in self.allow):
            return False
        if permission_key:
            return self.action(name, permission_key) != 'deny'
        return True

    def needs_confirm(self, name: str, permission_key: str,
                      path: str | None = None) -> bool:
        return self.action(name, permission_key, path) == 'ask'
