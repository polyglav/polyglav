import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import Config, config_bool, verbosity_level
from .cost import cache_reported, cached_tokens
from .runs import Run, RunRegistry
from .sessions.manager import SessionManager, coded_session_name
from .sessions import turns
from .commands.registry import CommandRegistry
from .commands.builtins import register_builtins
from .plugins.manager import PluginManager
from .ui import NullUI, StatusMetrics, glyph, glyph_map
from . import tool_log


@dataclass
class TurnResult:
    content: str | None = None
    thinking: str | None = None
    tool_calls: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duration: float = 0.0
    usage: dict | None = None
    context_tokens: int = 0
    compactions: list = field(default_factory=list)
    finish_reason: str = ''
    model: str = ''
    provider: str = ''
    session: str = ''
    status: str = 'ok'
    run_id: int | None = None
    streamed: bool = False

    def to_dict(self) -> dict:
        return {
            'content': self.content,
            'thinking': self.thinking,
            'tool_calls': self.tool_calls,
            'errors': self.errors,
            'duration': self.duration,
            'usage': self.usage,
            'context_tokens': self.context_tokens,
            'compactions': self.compactions,
            'finish_reason': self.finish_reason,
            'model': self.model,
            'provider': self.provider,
            'session': self.session,
            'status': self.status,
            'run_id': self.run_id,
            'streamed': self.streamed,
        }


CONTINUE_INSTRUCTION = ('Continue exactly where you stopped. '
                        'Do not repeat what was already written.')

_MAX_DENIED_STREAK = 3

_SUB_PERMISSION_NOTE = (
    'Operating note: you are a sub-agent with no interactive confirmation. '
    'Any tool in a category that resolves to "ask" is auto-denied. Do not '
    'retry a denied call. If a task truly needs such a tool, request it with '
    'ask(kind="permission", permission="<category>"), otherwise return a '
    'final answer with what you have.')


def _resolver_params(fn: Callable) -> set[str]:
    try:
        import inspect
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def _sanitize_session(name: str, limit: int = 64) -> str:
    cleaned = ''.join(c for c in str(name) if c.isalnum() or c in '-_.')
    cleaned = cleaned.strip('-_ .').replace(' ', '_')
    if not cleaned:
        cleaned = 'parent'
    if len(cleaned) > limit:
        cleaned = cleaned[-limit:]
    return cleaned


def _sub_session_name(parent: str, sessions_dir: Path) -> str:
    return coded_session_name('sub', parent, sessions_dir=sessions_dir)


class Engine:
    def __init__(self, config: Config, ui=None, plugin_manager=None,
                 provider=None, approve_models: bool = False,
                 runs: RunRegistry | None = None,
                 parent_run: int | None = None,
                 run: Run | None = None):
        self.config = config
        self.approve_models = approve_models
        self.role = ''
        self._paused = False
        self._provider_error = None
        self._ui = ui
        self._sub_run = False
        self._denied_streak = 0
        self._compact_warnings: set[str] = set()
        self._auto_compact_done = False
        self._observers: list[Callable[[dict], None]] = []
        self._request_round = 0
        self._compaction_seq = 0
        self._turn_deny_tools: set[str] = set()
        self._last_summary_usage: dict | None = None
        self._ask_ui = ui if getattr(ui, 'interactive', False) else None
        self._owns_provider = provider is None
        if plugin_manager is None:
            self._plugin_manager = PluginManager(config)
            self._plugin_manager.load()
        else:
            self._plugin_manager = plugin_manager
        if provider is None:
            self._reinit_provider()
        else:
            self.provider = provider
        self._seen_catalog_version = self._catalog_version()
        sessions_dir = config.local_path.parent / 'sessions'
        storage = self.config.get('session.storage', 'json')
        store = None
        if storage == 'sqlite':
            factory = self._plugin_manager.service('session_store')
            if factory is None:
                self.ui.info('Warning: SQLite session store plugin is not loaded, using JSON')
                storage = 'json'
            else:
                store = factory(sessions_dir)
        self.sessions = SessionManager(sessions_dir, storage=storage,
                                       store=store)
        self.current_session = self.sessions.create(role=self.role)
        self._bind_provider_session()
        self.runs = runs if runs is not None else RunRegistry()
        if run is not None:
            self.current_run: Run = run
        else:
            self.current_run = self.runs.start(
                role=self.role, session=self.current_session.session_name,
                parent=parent_run, session_id=self.current_session.session_id)
        self.registry = CommandRegistry(self)
        register_builtins(self.registry)
        self._plugin_manager.register_commands(self.registry)

    @property
    def ui(self):
        if getattr(self, '_ui', None) is None:
            self._ui = NullUI()
        return self._ui

    @property
    def models(self):
        if getattr(self, '_models', None) is None:
            from .models import ModelRegistry
            self._models = ModelRegistry()
        return self._models

    @property
    def providers(self):
        if getattr(self, '_providers', None) is None:
            from .providers.registry import ProviderRegistry
            self._providers = ProviderRegistry()
        return self._providers

    @property
    def roles(self):
        if getattr(self, '_roles', None) is None:
            factory = self._plugin_manager.service('role_registry')
            if factory is None:
                return None
            self._roles = factory(
                local_path=self.config.local_path.parent / 'roles.json')
            self._plugin_manager.register_roles(self._roles)
        return self._roles

    @property
    def teams(self):
        if getattr(self, '_teams', None) is None:
            factory = self._plugin_manager.service('team_registry')
            if factory is None:
                return None
            self._teams = factory(
                local_path=self.config.local_path.parent / 'teams.json')
            self._plugin_manager.register_teams(self._teams)
        return self._teams

    @property
    def memory(self):
        return self._plugin_manager.service('memory')

    @property
    def catalog(self):
        if getattr(self, '_catalog', None) is None:
            from .catalog import CatalogRegistry
            self._catalog = CatalogRegistry()
            self._plugin_manager.register_catalog(self._catalog)
        return self._catalog

    @property
    def skills(self):
        if getattr(self, '_skills', None) is None:
            factory = self._plugin_manager.service('skill_registry')
            if factory is None:
                return None
            self._skills = factory(
                local_dir=self.config.local_path.parent / 'skills')
            self._plugin_manager.register_skills(self._skills)
        return self._skills

    def _catalog_version(self) -> int:
        return int(getattr(self._plugin_manager, '_catalog_version', 0))

    def reload_catalogs(self) -> list[str]:
        reloaded: list[str] = []
        for attr, label in (('_roles', 'roles'), ('_teams', 'teams'),
                            ('_skills', 'skills')):
            registry = getattr(self, attr, None)
            if registry is None:
                continue
            registry.reload(self._plugin_manager)
            reloaded.append(label)
        self._seen_catalog_version = self._catalog_version()
        return reloaded

    def touch_catalogs(self) -> list[str]:
        self._plugin_manager._catalog_version = self._catalog_version() + 1
        return self.reload_catalogs()

    def _reload_catalogs_if_changed(self) -> None:
        if getattr(self, '_seen_catalog_version', None) != self._catalog_version():
            self.reload_catalogs()

    def _resolve_provider_factory(self, provider: str, base_url: str):
        from .providers import PROVIDERS, detect_provider
        from .providers.base import OpenAICompatibleProvider
        merged = dict(PROVIDERS)
        plugin_manager = getattr(self, '_plugin_manager', None)
        if plugin_manager is not None:
            for name, factory in plugin_manager.provider_classes().items():
                merged.setdefault(name, factory)
        factory = merged.get(provider)
        if factory is not None:
            return factory, provider, merged
        if provider and self.providers.find(provider) is not None:
            return OpenAICompatibleProvider, provider, merged
        detected = detect_provider(base_url, merged)
        self.ui.info(f'Unknown provider "{provider}" - using "{detected}" '
                     '(detected from base_url)')
        return merged.get(detected), detected, merged

    def unfold_ref(self, ref: str) -> tuple[str, str, str] | None:
        from .providers.registry import resolve_model_ref
        return resolve_model_ref(ref, self._merged_providers())

    def model_target(self, ref: str | None = None,
                     base_url: str | None = None) -> tuple[str, str, str]:
        from .providers import detect_provider
        raw = str(self.config.get('model') if ref is None else ref or '').strip()
        base = str(self.config.get('base_url')
                   if base_url is None else base_url or '').strip()
        merged = self._merged_providers()
        entry = None
        name = ''
        model = raw
        if raw and '/' in raw:
            name, _, model = raw.partition('/')
            entry = self.providers.find(name)
            factory = merged.get(name)
            if (factory is not None
                    and getattr(factory, 'DEFAULT_BASE_URL', '')):
                default = factory.DEFAULT_BASE_URL
                chosen = base or (entry.base_url if entry else '') or default
                if base and any(
                        other is not factory
                        and getattr(other, 'DEFAULT_BASE_URL', '') == base
                        for other in merged.values()):
                    chosen = default
                return name, chosen, model
            if entry is not None:
                return name, base or entry.base_url, model
            return name, base, model
        entry = self.providers.find('openai-compatible')
        if entry is not None and entry.base_url:
            base = base or entry.base_url
        provider = detect_provider(base, merged) if base else 'openai-compatible'
        return provider, base, model

    def _merged_providers(self) -> dict:
        from .providers import PROVIDERS
        merged = dict(PROVIDERS)
        plugin_manager = getattr(self, '_plugin_manager', None)
        if plugin_manager is not None:
            for name, factory in plugin_manager.provider_classes().items():
                merged.setdefault(name, factory)
        return merged

    def _ensure_model_approved(self, provider: str, model: str) -> bool:
        if self.models.find(provider, model) is not None:
            return True
        if getattr(self, 'approve_models', False):
            self.models.put(provider, model)
            return True
        if getattr(self.ui, 'interactive', False):
            try:
                ok = self.ui.confirm('model', f'Approve model "{provider}/{model}"')
            except KeyboardInterrupt:
                return False
            if ok:
                self.models.put(provider, model)
                return True
            return False
        return False

    def _record_model_outcome(self, status: str):
        provider, _, model = self.model_target()
        if not model:
            return
        if status in ('ok', 'truncated'):
            self.models.touch(provider, model)
        elif status == 'error':
            errors = self.current_session.errors
            message = errors[-1].get('message', '') if errors else ''
            self.models.record_failure(provider, model, message)

    def _reinit_provider(self):
        provider_name, base_url, model = self.model_target()
        factory, resolved, merged = self._resolve_provider_factory(
            provider_name, base_url)
        if factory is None:
            self._provider_error = f'No provider registered for "{provider_name}"'
            self.ui.info(f'[Error] {self._provider_error}')
            return
        if resolved != provider_name:
            provider_name = resolved
        if not base_url:
            base_url = self.providers.base_url_for(provider_name) or \
                getattr(factory, 'DEFAULT_BASE_URL', '')
        ref = str(self.config.get('model') or '')
        if ref and '/' in ref and not self._ensure_model_approved(
                provider_name, model):
            self._provider_error = (
                f'Model "{provider_name}/{model}" is not approved. Approve it '
                f'with /model {provider_name}/{model}, --model, or --approve-model.')
            return
        if getattr(self, 'approve_models', False) and model:
            self.models.put(provider_name, model)
        self._provider_error = None
        if base_url != self.config.get('base_url'):
            self.config.apply('base_url', base_url)
        api_key = self.providers.api_key_for(provider_name)
        self.provider = factory(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=self.config.get('temperature'),
            max_tokens=self.config.get('max_tokens'),
            reasoning=self.config.get('reasoning'),
            session_id=self._current_session_id(),
        )

    def _current_session_id(self) -> str:
        session = getattr(self, 'current_session', None)
        return session.session_id if session is not None else ''

    def _bind_provider_session(self):
        provider = getattr(self, 'provider', None)
        if provider is None or not hasattr(provider, 'session_id'):
            return
        if getattr(self, '_owns_provider', False):
            provider.session_id = self.current_session.session_id

    def check_connection(self, base_url: str | None = None, api_key: str | None = None,
                         model: str | None = None,
                         provider: str | None = None) -> tuple[bool, str, list[str]]:
        from .providers.base import _connection_message
        target_provider, target_url, target_model = self.model_target()
        provider = provider or target_provider
        base_url = target_url if base_url is None else base_url
        if not base_url:
            base_url = self.providers.base_url_for(provider)
        model = model or target_model
        if api_key is None:
            api_key = self.providers.api_key_for(provider)
        factory, _, _ = self._resolve_provider_factory(provider, base_url)
        if factory is None:
            return False, f'No provider registered for "{provider}"', []
        probe = factory(base_url=base_url, api_key=api_key, model=model)
        models, error = probe._fetch_models()
        if error:
            return False, error, []
        return True, _connection_message(models, model), models

    def list_models(self, provider: str | None = None,
                    base_url: str | None = None,
                    api_key: str | None = None,
                    model: str | None = None) -> tuple[list[str], str | None]:
        target_provider, target_url, target_model = self.model_target()
        provider = provider or target_provider
        base_url = target_url if base_url is None else base_url
        if not base_url:
            base_url = self.providers.base_url_for(provider)
        model = target_model if model is None else model
        if api_key is None:
            api_key = self.providers.api_key_for(provider)
        factory, _, _ = self._resolve_provider_factory(provider, base_url)
        if factory is None:
            return [], f'No provider registered for "{provider}"'
        probe = factory(base_url=base_url, api_key=api_key, model=model)
        return probe._fetch_models()

    def tool_log_path(self) -> Path:
        return tool_log.path_for(self.sessions.sessions_dir,
                                 self.current_session.session_name)

    def resolve_tool_ref(self, ref: str) -> str | None:
        return tool_log.resolve(ref, self.sessions.sessions_dir)

    def _store_tool_output(self, part: dict, output: str, turn_index: int,
                           part_index: int, name: str = '') -> str:
        if not isinstance(output, str) or not output:
            return ''
        if not self.config.get('tool_output_log', True):
            return ''
        try:
            stored = tool_log.append(
                self.sessions.sessions_dir, self.current_session.session_name,
                turn_index, part_index, name, output)
        except OSError:
            return ''
        part.update(stored)
        return str(stored['ref'])

    def session_auto_save(self):
        if not (self.current_session and self.current_session.turns):
            return
        self.sessions.save(self.current_session)

    def load_or_create_session(self, name: str | None = None):
        self.sessions.materialize(self.current_session)
        if name and self.sessions.read(name) is not None:
            self.current_session = self.sessions.load(name)
            for warning in self.catalog_warnings(self.current_session):
                self.ui.info(warning)
        elif name:
            self.current_session = self.sessions.create(name, role=self.role)
        else:
            self.current_session = self.sessions.create(role=self.role)
        self.current_run.session = self.current_session.session_name
        self.current_run.session_id = self.current_session.session_id
        self._bind_provider_session()
        return self.current_session

    def catalog_warnings(self, session) -> list[str]:
        warnings: list[str] = []
        if session.role and (self.roles is None
                             or self.roles.find(session.role) is None):
            warnings.append(
                f'Warning: role "{session.role}" no longer exists')
        if session.team and (self.teams is None
                             or self.teams.find(session.team) is None):
            warnings.append(
                f'Warning: team "{session.team}" no longer exists')
        return warnings

    def _grant(self) -> dict:
        ceiling = getattr(self, '_grant_ceiling', None)
        if isinstance(ceiling, dict):
            return dict(ceiling)
        from .modes import DEFAULT_WRITE_KEYS, read_keys
        mode = self._mode()
        self_perms = self._self_permissions()
        role_grant = self.config.get('grant_permission')
        role_grant = dict(role_grant) if isinstance(role_grant, dict) else {}
        out: dict = {}
        for key in read_keys(self.config):
            out[key] = self_perms.get(key, 'ask')
        for key in DEFAULT_WRITE_KEYS:
            out[key] = 'allow' if mode == 'write' else 'deny'
        for key, value in role_grant.items():
            out[key] = 'allow' if value is True else 'deny' if value is False else value
        if mode != 'write':
            for key in DEFAULT_WRITE_KEYS:
                out[key] = 'deny'
        return out

    def _mode(self) -> str:
        from .modes import mode_name
        return mode_name(self.config, self.current_session.mode or None)

    def _self_permissions(self) -> dict:
        from .modes import merge_policy
        return dict(merge_policy(self.config, self._mode())[0])

    def permission_keys(self) -> set:
        from .modes import DEFAULT_WRITE_KEYS, read_keys
        keys = set(read_keys(self.config)) | set(DEFAULT_WRITE_KEYS)
        registry = getattr(self, '_tool_registry', None)
        if registry is not None:
            for name in registry.primary_names():
                keys.add(registry.permission_for(name))
        return keys

    def permission_categories(self) -> set:
        keys = self.permission_keys()
        keys |= set((self.config.get('tool_permission') or {}).keys())
        return keys

    def grant_permission(self, permission: str, permission_key: str,
                         scope: str = 'once', origin: str = 'supervisor') -> bool:
        policy = getattr(self, '_tool_policy', None)
        if policy is None:
            return False
        registry = getattr(self, '_tool_registry', None)
        name = ''
        if (registry is not None and registry.is_registered(permission)
                and permission not in self.permission_categories()):
            name = registry.canonical_name(permission)
        policy.grant(name, permission_key, scope=scope, origin=origin)
        self.current_session.add_permission(
            permission, 'grant', 'granted', scope=scope, granted_by=origin)
        return True

    def _new_sub_engine(self, role_name: str, provider=None, mode: str = '',
                        skills: list | None = None,
                        task: str = '',
                        session_name: str | None = None, ui=None,
                        link_parent: bool = True,
                        run: Run | None = None) -> 'Engine':
        agent_role = (self.roles.find(role_name)
                      if role_name and self.roles is not None else None)
        if role_name and agent_role is None:
            raise ValueError(f'Unknown role: {role_name}')
        sub_config = Config(path=str(self.config.local_path.parent.parent))
        sub_config.apply('base_url', self.config.get('base_url') or '')
        system_prompt = (agent_role.system_prompt if agent_role
                         else str(self.config.get('system_prompt') or ''))
        names = list(agent_role.skills or []) if agent_role else []
        for name in (getattr(self, '_team_member_skills', {}) or {}).get(role_name, []):
            if name and name not in names:
                names.append(name)
        for name in (skills or []):
            if name and name not in names:
                names.append(name)
        if names and self.skills is not None:
            section_fn = self._plugin_manager.service('skills_section')
            section = section_fn(self.skills, names) if section_fn else ''
            if section:
                if system_prompt.strip():
                    system_prompt = system_prompt.rstrip() + '\n\n' + section
                else:
                    system_prompt = section
        memory_store = self.memory
        worktree = self.config.local_path.parent.parent
        if (agent_role is not None and memory_store is not None
                and memory_store.memory_enabled(sub_config, 'role')):
            text = memory_store.read_memory(worktree, 'role', role_name)
            section = memory_store.memory_section(text, self.config)
            if section:
                if system_prompt.strip():
                    system_prompt = system_prompt.rstrip() + '\n\n' + section
                else:
                    system_prompt = section
        sub_config.apply('system_prompt', system_prompt)
        if agent_role is not None and agent_role.model:
            sub_config.apply('model', agent_role.model)
        from .role_model import resolve_permissions, resolve_grant_ceiling
        parent_self = self._self_permissions()
        parent_grant = self._grant()
        role_carve = agent_role.tool_permission if agent_role else {}
        permissions = resolve_permissions(parent_self, parent_grant, role_carve)
        sub_config.apply('tool_permission', permissions)
        requested = role_carve or {}
        auto_denied = sorted(
            key for key, value in requested.items()
            if isinstance(value, str) and value in ('allow', 'ask')
            and permissions.get(key) == 'ask')
        if auto_denied:
            prompt = (sub_config.get('system_prompt') or '').rstrip()
            note = (_SUB_PERMISSION_NOTE
                    + ' Auto-denied categories: ' + ', '.join(auto_denied) + '.')
            sub_config.apply('system_prompt',
                             (prompt + '\n\n' + note).strip() if prompt else note)
        sub_config.apply('mode', mode or self._mode())
        ask_policy = dict(self.config.get('ask_policy') or {})
        if agent_role is not None and agent_role.ask_policy:
            ask_policy.update(agent_role.ask_policy)
        sub_config.apply('ask_policy', ask_policy)
        if provider is None and not (agent_role and agent_role.model):
            provider = self.provider
        sub = Engine(sub_config, ui=ui,
                     plugin_manager=self._plugin_manager, provider=provider,
                     runs=self.runs, parent_run=self.current_run.id, run=run)
        sub._observers = list(getattr(self, '_observers', []))
        sub.role = role_name
        sub.current_run.role = role_name
        sub.current_run.task = task
        sub._sub_run = True
        sub._team_member_skills = dict(getattr(self, '_team_member_skills', {}) or {})
        sub._ask_ui = getattr(self, '_ask_ui', None)
        role_grant = ((agent_role.grant_permission if agent_role else None)
                      or parent_grant)
        sub._grant_ceiling = resolve_grant_ceiling(
            parent_self, parent_grant, role_grant, permissions)
        sub._team_depth = getattr(self, '_team_depth', 0)
        sub._team_stack = list(getattr(self, '_team_stack', []))
        if session_name:
            sub.load_or_create_session(session_name)
        else:
            sub.load_or_create_session(_sub_session_name(
                self.current_session.session_name, self.sessions.sessions_dir))
        sub.current_session.mode = sub_config.get('mode') or ''
        sub.current_session.plan = getattr(self.current_session, 'plan', '')
        if link_parent:
            sub.current_session.parent_id = self.current_session.session_name
        return sub

    def resolve_target(self, target: str) -> tuple[Run | None, str]:
        text = str(target or '').strip()
        if not text:
            return None, ''
        low = text.lower()
        if low.startswith('session:'):
            name = text.split(':', 1)[1].strip()
            run = next((r for r in self.runs.runs() if r.session == name), None)
            return run, name
        explicit = text.startswith('#')
        token = text[1:] if explicit else text
        if token.isdigit():
            run = self.runs.get(int(token))
            if run is not None:
                return run, run.session
            if not explicit:
                return None, ''
        if explicit:
            run = self.runs.find_by_session_id(token)
            if run is not None:
                return run, run.session
            session = self.sessions.find_by_session_id(token)
            return None, session.session_name if session is not None else ''
        run = next((r for r in self.runs.runs() if r.session == text), None)
        if run is not None:
            return run, run.session
        session = self.sessions.read(text)
        return None, session.session_name if session is not None else ''

    def run_subagent(self, role_name: str, task: str, mode: str = '',
                     skills: list | None = None,
                     resume: str = '', context: str = 'continue') -> TurnResult:
        agent_role = (self.roles.find(role_name)
                      if role_name and self.roles is not None else None)
        if role_name and agent_role is None:
            raise ValueError(f'Unknown role: {role_name}')
        if not role_name:
            limit = int(self.config.get('delegate_depth', 1) or 0)
            if limit and getattr(self, '_delegate_depth', 0) >= limit:
                raise ValueError(
                    'delegate depth limit reached - ask the user before '
                    'spawning another sibling')
        if agent_role is not None and agent_role.model:
            provider, _, model = self.model_target(agent_role.model)
            if not self._ensure_model_approved(provider, model):
                raise ValueError(
                    f'Type "{role_name}" uses unapproved model "{model}" - '
                    'approve it first (/model, --approve-model, or /connect)')
        ctx = str(context or 'continue').strip().lower()
        run = None
        session_name = None
        if resume and ctx != 'new':
            run, session_name = self.resolve_target(resume)
            if not session_name:
                raise ValueError(f'Cannot resume "{resume}": not found')
        sub = self._new_sub_engine(
            role_name, mode=mode, skills=skills, task=task,
            session_name=session_name, run=run, link_parent=run is None)
        sub._delegate_depth = getattr(self, '_delegate_depth', 0) + 1
        if run is not None:
            self.runs.reactivate(run.id)
        if ctx == 'compact':
            sub.compact_session()
        label = getattr(self, '_stage_label', '') or (role_name or 'sibling')
        name = getattr(self, '_stage_name', '') or (role_name or 'sibling')
        is_sub = getattr(self.ui, 'is_sub_run', False)
        parent_ui = self.ui.parent if is_sub else self.ui
        depth = self.ui.depth + 1 if is_sub else 0
        if getattr(parent_ui, 'interactive', False):
            sub._ui = parent_ui.sub_ui(
                sub, role=role_name, label=name, depth=depth)
        metrics = StatusMetrics()
        sub._stream_metrics = metrics
        self.ui.status_begin(f'Call {label}', name=name, metrics=metrics)
        try:
            result = sub.chat(task, origin=self.role or 'root')
        except Exception:
            self.ui.status_end(ok=False)
            self.runs.finish(sub.current_run.id, 'error')
            raise
        ok = result.status in ('ok', 'truncated')
        result.streamed = bool(getattr(sub.ui, 'streamed', False))
        self.ui.status_end(self._run_stats(result), ok=ok)
        status = 'done' if result.status in ('ok', 'truncated') else 'error'
        self.runs.finish(sub.current_run.id, status, usage=result.usage,
                         duration=result.duration)
        if result.session and result.session not in self.current_session.sub_sessions:
            self.current_session.sub_sessions.append(result.session)
            self.session_auto_save()
        self._update_role_memory(role_name, result.session)
        return result

    def _note_stream(self, text):
        metrics = getattr(self, '_stream_metrics', None)
        if metrics is not None:
            metrics.add(text)

    def _run_stats(self, result: TurnResult) -> str:
        if verbosity_level(self.config, 'status') != 'on':
            return ''
        try:
            duration = float(getattr(result, 'duration', 0.0) or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        usage = getattr(result, 'usage', None) or {}
        total = usage.get('total_tokens')
        if total is None:
            total = (usage.get('prompt_tokens') or 0) + \
                (usage.get('completion_tokens') or 0)
        parts = [f'{duration:.1f}s']
        if total:
            parts.append(f'({int(total):,} tokens)')
        return ' '.join(parts)

    def _update_role_memory(self, role: str, session_name: str):
        memory_store = self.memory
        if memory_store is not None:
            memory_store.update_role_memory(self, role, session_name)

    def memorize(self, scope: str = 'role', name: str = '',
                 session=None) -> str:
        memory_store = self.memory
        if memory_store is None:
            return 'Memory plugin is not loaded'
        return memory_store.memorize(self, scope, name, session)

    def run_team(self, team, task: str, skills: list | None = None,
                 resume: str = '', context: str = 'continue') -> object:
        runner = self._plugin_manager.service('team_runner')
        if runner is None:
            raise ValueError('Team runner plugin is not loaded')
        return runner.run(self, team, task, skills=skills, resume=resume,
                          context=context)

    def _turn_meta(self) -> dict:
        provider, _, model = self.model_target()
        return {
            'model': model,
            'provider': provider,
            'mode': self._mode(),
            'reasoning': self.config.get('reasoning'),
        }

    def chat(self, text: str, origin: str = '',
             deny_tools: list[str] | None = None) -> TurnResult:
        if getattr(self, '_provider_error', None):
            return TurnResult(status='error',
                              errors=[{'code': '', 'message': self._provider_error}],
                              session=self.current_session.session_name)
        now = datetime.now(timezone.utc)
        self.current_session.add_user(
            text, timestamp=now.isoformat(timespec='seconds'), origin=origin,
            **self._turn_meta()
        )

        return self._agent_loop(deny_tools=deny_tools)

    def paused_turn(self):
        turn = self.current_session.open_turn()
        if turn is not None and turn.get('status') == 'paused':
            return turn
        return None

    def continue_turn(self) -> TurnResult | None:
        turn = self.paused_turn()
        if turn is None:
            self.ui.info('No paused turn to continue')
            return None
        self.current_session.add_part(turns.user_part(CONTINUE_INSTRUCTION))
        turn['status'] = 'running'
        self.current_run.status = 'running'
        self.session_auto_save()
        return self._agent_loop()

    def cancel_turn(self) -> bool:
        turn = self.paused_turn()
        if turn is None:
            self.ui.info('No paused turn to cancel')
            return False
        self.current_session.end_turn('cancelled')
        self.runs.finish(self.current_run.id, 'cancelled')
        self.session_auto_save()
        return True

    def chat_tool(self, name: str, arguments: dict) -> TurnResult:
        if getattr(self, '_provider_error', None):
            return TurnResult(status='error',
                              errors=[{'code': '', 'message': self._provider_error}],
                              session=self.current_session.session_name)
        if not self.config.get('tool_calling'):
            return TurnResult(status='error',
                              errors=[{'code': '', 'message': 'Tool calling is disabled'}],
                              session=self.current_session.session_name)
        self._init_tooling()
        if not self._tool_registry or not self._tool_policy:
            return TurnResult(status='error',
                              errors=[{'code': '', 'message': 'Tool calling is disabled'}],
                              session=self.current_session.session_name)
        if not self._tool_registry.is_registered(name):
            return TurnResult(status='error',
                              errors=[{'code': '', 'message': f'Unknown tool "{name}"'}],
                              session=self.current_session.session_name)
        return self._agent_loop(seed_tool=(name, arguments))

    def _agent_loop(self, seed_tool: tuple[str, dict] | None = None,
                    deny_tools: list[str] | None = None) -> TurnResult:
        self._denied_streak = 0
        self._auto_compact_done = False
        self._turn_compactions: list[dict] = []
        self._request_round = 0
        self._turn_deny_tools = {str(name) for name in (deny_tools or [])}
        self._round_weights, self._last_prompt_tokens = self._compact_history()
        if self.current_session.open_turn() is None:
            self.current_session.start_turn(**self._turn_meta())
        tools_schema = self._init_tooling()
        turn_start = datetime.now(timezone.utc)
        usage_total = None
        requests = 0

        def merge_usage(value):
            nonlocal usage_total, requests
            if not isinstance(value, dict):
                return
            requests += 1
            if usage_total is None:
                usage_total = {'prompt_tokens': 0, 'completion_tokens': 0,
                               'reasoning_tokens': 0, 'total_tokens': 0,
                               'requests': 0}
            prompt = value.get('prompt_tokens')
            if isinstance(prompt, int) and prompt > 0:
                usage_total['prompt_tokens'] += prompt
                usage_total['context_tokens'] = prompt
                last = getattr(self, '_last_prompt_tokens', 0)
                if last > 0:
                    self._record_round_weight(prompt - last)
                self._last_prompt_tokens = prompt
            completion = value.get('completion_tokens')
            if isinstance(completion, int) and completion > 0:
                usage_total['completion_tokens'] += completion
            details = value.get('completion_tokens_details') or {}
            thinking = details.get('reasoning_tokens')
            if not isinstance(thinking, int):
                thinking = value.get('reasoning_tokens')
            if isinstance(thinking, int) and thinking > 0:
                usage_total['reasoning_tokens'] += thinking
            total = value.get('total_tokens')
            if not isinstance(total, int):
                total = ((prompt or 0) + (completion or 0))
            if total:
                usage_total['total_tokens'] += total
            usage_total['requests'] = requests

        reason = ''
        status = 'ok'
        paused = False
        content = ''
        thinking = ''
        executed_tool_calls: list[dict] = []
        err_base = len(self.current_session.errors)

        try:
            if seed_tool is not None:
                name, args = seed_tool
                executed_tool_calls += self._execute_tool_calls(
                    [{'function': {'name': name, 'arguments': json.dumps(args)},
                      'id': 'call_seed'}])
            while True:
                self._reload_catalogs_if_changed()
                if self._auto_compact_due(usage_total):
                    self._auto_compact(usage_total)
                think_start: datetime | None = None

                def feed_thinking(text):
                    nonlocal think_start
                    if think_start is None:
                        think_start = datetime.now(timezone.utc)
                        self.ui.thinking_begin()
                    self.ui.thinking(text)

                def end_thinking():
                    nonlocal think_start
                    if think_start is not None:
                        dur = round((datetime.now(timezone.utc) - think_start)
                                    .total_seconds(), 1)
                        think_start = None
                        self.ui.thinking_end(dur)

                messages = self._provider_messages()
                tools_schema = self._tool_schema()
                max_attempts = 1 + max(0, int(self.config.get('stream_retries', 2)))
                retry_delay = max(0.0, float(self.config.get('stream_retry_delay', 0.5)))
                max_continues = max(0, int(self.config.get('auto_continue_max', 2)))
                content = ''
                thinking = ''
                attempt = 1
                consumes = 0
                while True:
                    stream_messages = messages
                    if consumes > 0:
                        assistant = {'role': 'assistant', 'content': content}
                        if thinking:
                            assistant['thinking'] = thinking
                        stream_messages = self._provider_messages() + [
                            assistant,
                            {'role': 'user', 'content': CONTINUE_INSTRUCTION},
                        ]
                    self._request_round += 1
                    round_number = self._request_round
                    turn = self.current_session.open_turn()
                    turn_index = turn.get('index', 0) if turn else 0
                    request_usage = None
                    if self._has_observers():
                        self._emit({
                            'type': 'request_start',
                            'turn': turn_index,
                            'round': round_number,
                            'ctx_tokens': self._context_tokens(),
                            'context_blocks': self._provider_blocks(),
                        })
                    s_content = ''
                    s_thinking = ''
                    in_thinking = False
                    tool_calls_detected = False
                    got_done = False
                    aborted = False
                    try:
                        for event in self.provider.chat(stream_messages, tools=tools_schema):
                            t = event.get('type', '')
                            if t == 'thinking':
                                s_thinking += event['content']
                                self._note_stream(event['content'])
                                feed_thinking(event['content'])
                            elif t == 'token':
                                token = event['content']
                                while token:
                                    if not in_thinking:
                                        marker = '<thinking>'
                                        idx = token.find(marker)
                                        if idx != -1:
                                            before = token[:idx]
                                            if before:
                                                end_thinking()
                                                s_content += before
                                                self._note_stream(before)
                                                self.ui.token(before)
                                            s_thinking += marker
                                            feed_thinking(marker)
                                            token = token[idx + len(marker):]
                                            in_thinking = True
                                        else:
                                            end_thinking()
                                            s_content += token
                                            self._note_stream(token)
                                            self.ui.token(token)
                                            token = ''
                                    else:
                                        closer = '</thinking>'
                                        idx = token.find(closer)
                                        if idx != -1:
                                            before = token[:idx]
                                            if before:
                                                s_thinking += before
                                                feed_thinking(before)
                                            end_thinking()
                                            token = token[idx + len(closer):]
                                            in_thinking = False
                                        else:
                                            s_thinking += token
                                            feed_thinking(token)
                                            token = ''
                            elif t == 'tool_call_delta':
                                self.ui.tool_call_progress(
                                    event.get('name', 'tool'),
                                    int(event.get('chars') or 0))
                            elif t == 'tool_calls':
                                tool_calls_detected = True
                                request_usage = event.get('usage') or request_usage
                                merge_usage(event.get('usage'))
                                end_thinking()
                                executed_tool_calls += self._execute_tool_calls(
                                    event['tool_calls'], s_thinking or None,
                                    usage=event.get('usage'))
                                if (getattr(self, '_sub_run', False)
                                        and self._denied_streak >= _MAX_DENIED_STREAK):
                                    msg = (f'Stopped after {self._denied_streak} '
                                           'consecutive permission denials - this '
                                           'sub-agent run has no interactive '
                                           'confirmation')
                                    self.current_session.add_error(0, msg)
                                    self.ui.error(0, msg)
                                    status = 'error'
                                    aborted = True
                                break
                            elif t == 'error':
                                code = event.get('code', '')
                                msg = event.get('message', 'Unknown error')
                                end_thinking()
                                self.current_session.add_error(code, msg)
                                self.ui.error(code, msg)
                                status = 'error'
                                aborted = True
                                break
                            elif t == 'done':
                                got_done = True
                                request_usage = event.get('usage') or request_usage
                                merge_usage(event.get('usage'))
                                reason = event.get('reason', '')
                                end_thinking()
                                break
                    except KeyboardInterrupt:
                        end_thinking()
                        content += s_content
                        thinking += s_thinking
                        if getattr(self, '_sub_run', False):
                            self.ui.info('(cancelled)')
                            status = 'cancelled'
                        else:
                            self.ui.info('(paused)')
                            status = 'paused'
                            paused = True
                        aborted = True
                    except Exception as e:
                        end_thinking()
                        content += s_content
                        thinking += s_thinking
                        self.current_session.add_error(0, f'Agent loop failed: {e}')
                        self.ui.error(0, str(e))
                        status = 'error'
                        aborted = True
                    if self._has_observers():
                        usage = request_usage or {}
                        prompt = usage.get('prompt_tokens')
                        prompt = prompt if isinstance(prompt, int) else 0
                        cached = cached_tokens(usage)
                        completion = usage.get('completion_tokens')
                        completion = completion if isinstance(completion, int) else 0
                        request_status = (
                            'tool_calls' if tool_calls_detected
                            else 'error' if aborted else 'done')
                        self._emit({
                            'type': 'request_end',
                            'turn': turn_index,
                            'round': round_number,
                            'status': request_status,
                            'finish_reason': reason,
                            'usage': request_usage,
                            'input_tokens': prompt,
                            'cache_read_tokens': cached,
                            'cache_reported': cache_reported(usage),
                            'completion_tokens': completion,
                            'ctx_tokens': self._context_tokens(request_usage),
                        })
                    if aborted:
                        break
                    if tool_calls_detected:
                        break
                    content += s_content
                    thinking += s_thinking
                    if got_done:
                        if reason == 'length':
                            if content and max_continues > 0 and consumes < max_continues:
                                consumes += 1
                                attempt = 1
                                self.ui.info(f'(output truncated - continuing '
                                             f'{consumes}/{max_continues})')
                                continue
                            limit = self.config.get('max_tokens')
                            if limit > 0:
                                msg = ('Assistant output truncated: max_tokens limit reached '
                                       f'({limit})')
                                self.ui.warning('Assistant output truncated (max_tokens reached); '
                                                'use /config max_tokens N')
                            else:
                                msg = ("Assistant output truncated: the provider's default "
                                       'max_tokens limit was reached')
                                self.ui.warning('Assistant output truncated (provider max_tokens '
                                                'limit reached); set /config max_tokens N to raise it')
                            self.current_session.add_error(0, msg)
                            status = 'truncated'
                            break
                        if not content and not thinking:
                            if attempt < max_attempts:
                                attempt += 1
                                if retry_delay:
                                    time.sleep(retry_delay)
                                continue
                            msg = 'Assistant returned an empty response'
                            self.current_session.add_error(0, msg)
                            self.ui.warning(msg)
                            status = 'empty'
                        break
                    if not content and attempt < max_attempts:
                        self.ui.info(f'(stream ended before a completion event - retrying '
                                     f'{attempt}/{max_attempts - 1})')
                        attempt += 1
                        if retry_delay:
                            time.sleep(retry_delay)
                        continue
                    msg = 'Stream ended before a completion event'
                    self.current_session.add_error(0, msg)
                    if executed_tool_calls:
                        self.ui.warning(f'{msg} - tool results are saved, '
                                        'send "continue" to retry the answer')
                    else:
                        self.ui.warning(msg)
                    status = 'error'
                    break
                if aborted or not tool_calls_detected:
                    break
        except KeyboardInterrupt:
            if getattr(self, '_sub_run', False):
                self.ui.info('(cancelled)')
                status = 'cancelled'
            else:
                self.ui.info('(paused)')
                status = 'paused'
                paused = True
        finally:
            if content or thinking:
                end = datetime.now(timezone.utc)
                duration = round((end - turn_start).total_seconds(), 1)
                stamp = end.isoformat(timespec='seconds')
                self.current_session.add_thinking(thinking, stamp)
                if content:
                    self.current_session.add_text(content, stamp)
                counts = self._usage_counts(usage_total)
                counts['tree'] = self._tree_tokens(usage_total)
                self.ui.footer(duration, counts)
            if paused:
                turn = self.current_session.open_turn()
                if turn is not None:
                    turn['status'] = 'paused'
                    self.current_session._touch()
            else:
                self.current_session.end_turn(
                    status, usage=usage_total,
                    context_tokens=self._context_tokens(usage_total),
                    finish_reason=reason)
                self._record_model_outcome(status)
            self.session_auto_save()

        usage = usage_total
        duration = round((datetime.now(timezone.utc) - turn_start).total_seconds(), 1)
        model_target = self.model_target()
        return TurnResult(
            content=content or None,
            thinking=thinking or None,
            tool_calls=executed_tool_calls,
            errors=self.current_session.errors[err_base:],
            duration=duration,
            usage=usage,
            context_tokens=self._context_tokens(usage),
            compactions=list(getattr(self, '_turn_compactions', [])),
            finish_reason=reason,
            model=model_target[2],
            provider=model_target[0],
            session=self.current_session.session_name,
            status=status,
            run_id=self.current_run.id,
        )

    def _execute_tool_calls(self, tcs: list[dict], thinking: str = '',
                            usage: dict | None = None) -> list[dict]:
        self.current_session.add_thinking(thinking)
        self._round_usage = usage
        executed: list[dict] = []
        for index, tc in enumerate(tcs):
            name = tc['function']['name']
            try:
                args = json.loads(tc['function']['arguments'])
            except (json.JSONDecodeError, KeyError):
                args = {}
            if (self.config.get('query_refine')
                    and self._tool_registry.refine_required(name)
                    and len(args.get('query', '').split()) <= self.config.get('query_refine_min_words', 3)):
                original = args['query']
                args['query'] = self._refine_query(args['query'])
                if args['query'] != original:
                    self.ui.tool_refine(original, args['query'])
            part = self.current_session.add_tool(name, args,
                                                 call_id=tc.get('id', ''))
            if index == 0 and isinstance(usage, dict):
                part['usage'] = dict(usage)
            tool_start = time.monotonic()
            output = self._run_tool(name, args)
            result_tokens = max(1, len(output) // 4) if output else 0
            refs = self._tool_registry.refs_for(name, args, output)
            if refs:
                part['refs'] = refs
            duration = round(time.monotonic() - tool_start, 1)
            if (self._tool_registry.echo_for(name) and output
                    and not self._tool_registry.is_note_result(name, output)
                    and not output.startswith(('[cancelled]', 'Error'))):
                if self._tool_registry.is_error_result(name, output):
                    self.ui.tool_error_result(output)
                else:
                    self.ui.tool_result(output)
            executed.append({'name': name, 'arguments': args})
            analysis = None
            turn = self.current_session.open_turn()
            turn_index = turn.get('index', 0) if turn else 0
            part_index = max(0, len(turn.get('parts') or []) - 1) if turn else 0
            ref = self._store_tool_output(part, output, turn_index, part_index, name)
            stored = self._with_output_ref(output, ref)
            is_error = output.startswith('Error')
            part['result_tokens'] = result_tokens
            turns.finish_tool(part, stored, is_error=is_error,
                              analysis=analysis, duration=duration)
            if self._has_observers():
                info = self._tool_registry.info(name) or {}
                path_arg = self._tool_registry.path_arg_for(name)
                path = args.get(path_arg) if path_arg else ''
                self._emit({
                    'type': 'tool_end',
                    'turn': turn_index,
                    'round': getattr(self, '_request_round', 0),
                    'part': part_index,
                    'name': name,
                    'category': info.get('category', ''),
                    'path': path or '',
                    'arguments': args,
                    'output': output,
                    'result_tokens': result_tokens,
                    'is_error': is_error,
                    'duration': duration,
                })
        return executed

    @staticmethod
    def _with_output_ref(output: str, ref: str) -> str:
        if ref and '... (truncated)' in output:
            return f'{output}\n[full output: {ref}]'
        return output

    def _init_tooling(self):
        if not self.config.get('tool_calling'):
            self._tool_registry = None
            self._tool_policy = None
            return None
        from .tools.registry import ToolRegistry
        from .tools.policy import ToolPolicy
        from .tools.delegate import register_delegate_tool
        from .tools.ask import register_ask_tool
        from .tools.catalog import register_catalog_tool
        from .modes import merge_policy, mode_cap, read_keys
        mode = self._mode()
        self._tool_registry = ToolRegistry(engine=self)
        register_delegate_tool(self._tool_registry, self)
        register_ask_tool(self._tool_registry, self)
        register_catalog_tool(self._tool_registry, self)
        plugin_manager = getattr(self, '_plugin_manager', None)
        if plugin_manager is not None:
            plugin_manager.register_tools(self._tool_registry)
        permissions, allow, deny = merge_policy(self.config, mode)
        resolvers = {}
        for n in self._tool_registry.names():
            fn = self._tool_registry.resolver_for(n)
            if fn is None:
                continue
            params = _resolver_params(fn)
            kwargs = {}
            if '_permissions' in params:
                kwargs['_permissions'] = permissions
            if '_config' in params:
                kwargs['_config'] = self.config
            if kwargs:
                fn = (lambda f, kw=kwargs: lambda args: f(args, **kw))(fn)
            resolvers[n] = fn
        self._tool_policy = ToolPolicy(
            permissions=permissions,
            allow=allow,
            deny=deny,
            worktree=self.config.local_path.parent.parent,
            resolvers=resolvers,
            mode=mode,
            read_keys=read_keys(self.config),
            cap=mode_cap(self.config, mode),
        )
        return self._tool_schema()

    def _tool_schema(self):
        registry = getattr(self, '_tool_registry', None)
        policy = getattr(self, '_tool_policy', None)
        if registry is None or policy is None:
            return []
        denied = getattr(self, '_turn_deny_tools', set())
        if '*' in denied:
            return []
        allowed = {n for n in registry.names()
                   if registry.canonical_name(n) not in denied
                   and policy.allowed(n, registry.permission_for(n))}
        return registry.schema_filtered(allowed)

    def _run_tool(self, name: str, args: dict, echo: bool = True) -> str:
        registry = self._tool_registry
        policy = self._tool_policy
        denied = getattr(self, '_turn_deny_tools', set())
        if '*' in denied or registry.canonical_name(name) in denied:
            return f'Error: tool "{name}" is disabled for this turn'
        if not registry.is_registered(name):
            available = ', '.join(registry.primary_names())
            result = f'Error: unknown tool "{name}"'
            if available:
                result += f'. Available tools: {available}'
            self.ui.tool_error(result)
            return result
        cleaned = registry.clean_args(name, args)
        path_arg = registry.path_arg_for(name)
        path = cleaned.get(path_arg) if path_arg else None
        permission_key = registry.permission_for(name)
        grant = policy.grant_for(name, permission_key)
        action = policy.action(name, permission_key, path, args)
        if action == 'deny':
            self._log_permission(name, action, 'denied', path)
            return f'Error: tool "{name}" is disabled by tool policy'
        if action == 'ask' and registry.confirm_for(name):
            if getattr(self, '_sub_run', False):
                self._log_permission(name, action, 'declined', path)
                self._denied_streak = getattr(self, '_denied_streak', 0) + 1
                return (f'Error: permission denied - "{name}" needs category '
                        f'"{permission_key}", which a sub-agent run cannot '
                        f'confirm. Do not retry. Use '
                        f'ask(kind="permission", permission="{permission_key}") '
                        f'to request it, or return a final answer.')
            try:
                granted = self._confirm_tool(name, args)
            except KeyboardInterrupt:
                self._log_permission(name, action, 'declined', path)
                raise
            self._log_permission(name, action, 'granted' if granted else 'declined', path)
            if not granted:
                return f'[cancelled] User declined the {name} call'
        elif grant is not None:
            policy.consume(name, permission_key)
            self._log_permission(name, 'grant', 'granted', path,
                                 scope=grant.get('scope'),
                                 granted_by=grant.get('origin'))
        else:
            self._log_permission(name, action, 'granted', path)
        self._show_tool_status(name, args)
        result = registry.execute(name, args, config=self.config, echo=echo)
        if result.startswith('Error'):
            self.ui.tool_error(result)
        elif registry.is_note_result(name, result):
            self.ui.tool_note(result)
        self._denied_streak = 0
        return result

    def _log_permission(self, name: str, action: str, decision: str,
                        path: str | None = None, **extra):
        self.current_session.add_permission(name, action, decision, path, **extra)

    def _confirm_tool(self, name: str, args: dict) -> bool:
        key_arg = self._tool_registry.key_arg_for(name)
        label = name
        if key_arg and args.get(key_arg):
            value = str(args[key_arg])
            from .tools.registry import shorten
            label = f'{name} {shorten(value, 80)}'
        params = self._tool_registry.params_str(name, args)
        if params and verbosity_level(self.config, 'tools') == 'full':
            label = f'{label} [{params}]'
        return self.ui.confirm(name, label)

    def _show_tool_status(self, name, arguments):
        level = verbosity_level(self.config, 'tools')
        if level == 'off' or self._tool_registry.silent_for(name):
            return
        value, body = self._tool_registry.status_parts(name, arguments)
        activity = self._tool_registry.activity(
            name, arguments, glyphs=glyph_map(self.config))
        if activity is not None:
            glyph, verb, label, params = activity
            if params and level == 'full':
                label = f'{label} [{params}]'
            if level == 'full':
                usage = getattr(self, '_round_usage', None) or {}
                total = usage.get('total_tokens')
                if total:
                    label = f'{label} ({int(total):,} tokens)'
            self.ui.activity(glyph, verb, label, body)
        else:
            if level == 'full':
                usage = getattr(self, '_round_usage', None) or {}
                total = usage.get('total_tokens')
                if total:
                    value = f'{value} ({int(total):,} tokens)'
            self.ui.tool_status(name, value, body)

    def _refine_query(self, query: str) -> str:
        context_count = self.config.get('query_refine_context', 4)
        context_msgs = self._provider_messages()[-context_count:] if context_count > 0 else []
        refine_sys = "You are a search query optimizer. Rewrite the user's query to be more specific and standalone based on the conversation context. Return ONLY the rewritten query, nothing else."
        refined = self.provider.chat_nonstreaming(
            [{'role': 'system', 'content': refine_sys}] + context_msgs + [{'role': 'user', 'content': query}],
            tools=None,
        )
        refined_query = (refined.get('content') or query).strip().strip('"\'')
        return refined_query if refined_query else query

    def _provider_messages(self) -> list[dict]:
        from .modes import system_instruction, instructions_file_section
        summary, boundary_turn, boundary_part = turns.compaction(
            self.current_session.turns)
        out = []
        if summary:
            out.append({
                'role': 'system',
                'content': 'Summary of earlier conversation:\n\n' + summary,
            })
        instructions = instructions_file_section(self.config)
        if instructions:
            out.append({'role': 'system', 'content': instructions})
        instruction = system_instruction(self.config, self._mode())
        if instruction:
            out.append({'role': 'system', 'content': instruction})
        service = self._plugin_manager.service('bookkeeping')
        plan = (service.plan_context(self.config, self.current_session)
                if service is not None else '')
        if plan:
            out.append({'role': 'system', 'content': plan})
        todo = (service.todo_context(self.config, self.current_session)
                if service is not None else '')
        if todo:
            out.append({'role': 'system', 'content': todo})
        for turn in self.current_session.turns:
            index = turn.get('index', 0)
            if boundary_turn and index < boundary_turn:
                continue
            if boundary_turn and index == boundary_turn:
                out.extend(turns.turn_to_provider(
                    turn, start_part=boundary_part, keep_prelude=True))
            else:
                out.extend(turns.turn_to_provider(turn))
        return out

    def _block(self, kind: str, content: str, turn: int = 0,
               part: int | None = None) -> dict:
        text = content or ''
        return {
            'kind': kind,
            'content': text,
            'tokens': max(1, len(text) // 4) if text else 0,
            'turn': turn,
            'part': part,
        }

    def _turn_blocks(self, turn: dict, start_part: int = 0,
                     keep_prelude: bool = False) -> list[dict]:
        parts = turn.get('parts') or []
        index = turn.get('index', 0)
        blocks: list[dict] = []
        i = 0
        if start_part > 0 and keep_prelude:
            while i < start_part:
                part = parts[i]
                kind = part.get('type')
                if kind == 'user':
                    blocks.append(self._block(
                        'user', part.get('text') or '', index, i))
                elif kind == 'system':
                    blocks.append(self._block(
                        'system', part.get('text') or '', index, i))
                i += 1
        else:
            i = max(0, start_part)
        while i < len(parts):
            part = parts[i]
            kind = part.get('type')
            if kind == 'user':
                blocks.append(self._block(
                    'user', part.get('text') or '', index, i))
            elif kind == 'system':
                blocks.append(self._block(
                    'system', part.get('text') or '', index, i))
            elif kind == 'thinking':
                blocks.append(self._block(
                    'thinking', part.get('text') or '', index, i))
            elif kind == 'text':
                blocks.append(self._block(
                    'assistant', part.get('text') or '', index, i))
            elif kind == 'tool':
                value = part.get('input')
                call_text = json.dumps(value) if value is not None else ''
                blocks.append(self._block(
                    'tool_call', call_text, index, i))
                blocks.append(self._block(
                    'tool', part.get('output') or '', index, i))
            i += 1
        return blocks

    def _provider_blocks(self) -> list[dict]:
        from .modes import system_instruction, instructions_file_section
        summary, boundary_turn, boundary_part = turns.compaction(
            self.current_session.turns)
        blocks: list[dict] = []
        if summary:
            blocks.append(self._block(
                'summary', 'Summary of earlier conversation:\n\n' + summary))
        instructions = instructions_file_section(self.config)
        if instructions:
            blocks.append(self._block('instructions', instructions))
        instruction = system_instruction(self.config, self._mode())
        if instruction:
            blocks.append(self._block('system', instruction))
        service = self._plugin_manager.service('bookkeeping')
        plan = (service.plan_context(self.config, self.current_session)
                if service is not None else '')
        if plan:
            blocks.append(self._block('plan', plan))
        todo = (service.todo_context(self.config, self.current_session)
                if service is not None else '')
        if todo:
            blocks.append(self._block('todo', todo))
        for turn in self.current_session.turns:
            index = turn.get('index', 0)
            if boundary_turn and index < boundary_turn:
                continue
            if boundary_turn and index == boundary_turn:
                blocks.extend(self._turn_blocks(
                    turn, boundary_part, keep_prelude=True))
            else:
                blocks.extend(self._turn_blocks(turn))
        return blocks

    def context_snapshot(self) -> dict:
        return {
            'messages': self._provider_messages(),
            'blocks': self._provider_blocks(),
            'tokens': self._context_tokens(),
        }

    def add_observer(self, fn: Callable[[dict], None]) -> None:
        observers = getattr(self, '_observers', None)
        if observers is None:
            observers = self._observers = []
        if fn not in observers:
            observers.append(fn)

    def _emit(self, event: dict) -> None:
        for fn in list(getattr(self, '_observers', [])):
            try:
                fn(event)
            except Exception:
                pass

    def _has_observers(self) -> bool:
        return bool(getattr(self, '_observers', []))

    def _clean_messages(self, msgs: list[dict]) -> list[dict]:
        out = []
        for m in msgs:
            role = m.get('role')
            if role == 'command':
                if m.get('result'):
                    out.append({
                        'role': 'system',
                        'content': 'Summary of earlier conversation:\n\n' + m['result'],
                    })
                continue
            if role == 'assistant':
                content = m.get('content')
                if m.get('tool_calls'):
                    if content:
                        out.append({'role': 'assistant', 'content': content})
                    continue
                out.append(m)
            elif role == 'tool':
                out.append({'role': 'user', 'content': f"[tool result] {m.get('content') or ''}"})
            else:
                out.append(m)
        return out

    def _summarize(self, msgs: list[dict], previous: str = '') -> str | None:
        self._last_summary_usage = None
        clean = self._clean_messages(msgs)
        prompt = (
            "Summarize the conversation up to this point into a concise summary that "
            "preserves key facts, decisions, tool findings, and open questions. "
            "Preserve the original user task and its constraints. "
            "The summary will be the only remaining record of the earlier conversation. "
            "Return only the summary text, nothing else."
        )
        if previous:
            prompt += ("\n\nPrevious summary:\n\n" + previous +
                       "\n\nMerge the previous summary and the new messages into "
                       "one updated summary.")
        try:
            result = self.provider.chat_nonstreaming(
                [{'role': 'system', 'content': prompt}] + clean,
                tools=None,
            )
        except Exception:
            result = {'error': {'code': 0, 'message': 'Compaction request failed'}}
        if isinstance(result, dict) and result.get('error'):
            err = result['error']
            code = err.get('code', '')
            msg = err.get('message', 'Unknown error')
            self.ui.error(code, msg)
            self.ui.info('Compaction failed - context unchanged')
            return None
        summary = (result.get('content') or '').strip()
        if not summary:
            self.ui.info('Compaction failed - context unchanged')
            return None
        self._last_summary_usage = (result.get('usage')
                                    if isinstance(result, dict) else None)
        return summary

    def summary_session(self):
        base = list(self.current_session.turns)
        if base and turns.command_only(base[-1]):
            base = base[:-1]
        if not base:
            self.ui.info('Nothing to summarize')
            return
        self._last_summary_usage = None
        summary = self._summarize(turns.provider_messages(base))
        if summary is None:
            return
        self.current_session.set_summary(
            summary, usage=getattr(self, '_last_summary_usage', None))
        try:
            header = (f'# Summary: {self.current_session.session_name}\n\n'
                      f'- Version: {self.current_session.version or "-"}\n\n')
            self.sessions.write_summary(
                self.current_session.session_name, header + summary)
        except OSError:
            pass
        self.ui.info('--- summary ---')
        self.ui.info(summary)
        self.session_auto_save()

    def _context_window(self) -> int:
        provider, _, model = self.model_target()
        entry = (self.models.find(provider, model)
                 if self.models is not None else None)
        if entry is not None:
            try:
                value = int(entry.context_window or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        try:
            value = int(self.config.get('context_window', 0) or 0)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _compact_limit(self) -> int:
        raw = self.config.get('compact_at', 0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0
        if value <= 0:
            return 0
        if value > 1:
            return int(value)
        if value == 1:
            self._warn_compact_once(
                'ambiguous',
                'compact_at 1.0 is ambiguous; use a value below 1 for a '
                'fraction or above 1 for absolute tokens')
            return 0
        window = self._context_window()
        if window <= 0:
            self._warn_compact_once(
                'window',
                'compact_at is relative but context_window is unknown; set '
                'context_window or use an absolute compact_at')
            return 0
        return max(1, int(value * window))

    def _warn_compact_once(self, key: str, message: str):
        warnings = getattr(self, '_compact_warnings', None)
        if warnings is None:
            warnings = self._compact_warnings = set()
        if key in warnings:
            return
        warnings.add(key)
        self.ui.warning(message)

    def _auto_compact_due(self, usage: dict | None) -> bool:
        if not config_bool(self.config.get('compact_auto', True)):
            return False
        if getattr(self, '_auto_compact_done', False):
            return False
        limit = self._compact_limit()
        if limit <= 0:
            return False
        current = self._context_tokens(usage)
        projected = current + self._average_round_weight()
        return current >= limit or projected >= limit

    def _average_round_weight(self) -> int:
        before = max(0, int(self.config.get('compact_before', 3) or 0))
        if before <= 0:
            return 0
        weights = [w for w in getattr(self, '_round_weights', []) if w > 0]
        if not weights:
            return 0
        window = weights[-before:]
        return int(sum(window) / len(window))

    def _record_round_weight(self, weight: int) -> None:
        before = max(0, int(self.config.get('compact_before', 3) or 0))
        if before <= 0:
            return
        weights = getattr(self, '_round_weights', None)
        if weights is None:
            weights = self._round_weights = []
        weights.append(max(0, int(weight)))
        del weights[:-before]

    def _compact_history(self) -> tuple[list[int], int]:
        before = max(0, int(self.config.get('compact_before', 3) or 0))
        contexts = []
        for turn in self.current_session.turns:
            if turns.command_only(turn):
                continue
            try:
                value = int(turn.get('context_tokens') or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                contexts.append(value)
        weights = [max(0, later - earlier)
                   for earlier, later in zip(contexts, contexts[1:])]
        last = contexts[-1] if contexts else 0
        if before <= 0:
            return [], last
        return weights[-before:], last

    def _auto_compact(self, usage: dict | None):
        self._auto_compact_done = True
        before = self._context_tokens(usage)
        record = self.compact_session(auto=True)
        if record:
            compactions = getattr(self, '_turn_compactions', None)
            if compactions is not None:
                compactions.append(record)
            after = self._context_tokens()
            self.ui.info(f'Auto-compacted at {before:,} tokens '
                         f'(now {after:,})')

    def _compact_rounds(self, base: list[dict]) -> list[tuple[int, int]]:
        rounds: list[tuple[int, int]] = []
        for turn in base:
            if turns.command_only(turn):
                continue
            index = turn.get('index', 0)
            for start in turns.round_starts(turn):
                rounds.append((index, start))
        return rounds

    def _compact_boundary(self, base: list[dict],
                          keep: int) -> tuple[int, int] | None:
        rounds = self._compact_rounds(base)
        if not rounds:
            return None
        if keep <= 0:
            last_turn = rounds[-1][0]
            first = next((start for index, start in rounds
                          if index == last_turn), None)
            if first is None:
                return None
            return last_turn, first
        if len(rounds) <= keep:
            return None
        return rounds[-keep]

    def compact_session(self, auto: bool = False) -> dict | None:
        keep = max(0, int(self.config.get('compact_keep', 1)))
        base = list(self.current_session.turns)
        boundary = self._compact_boundary(base, keep)
        if boundary is None:
            if not auto:
                self.ui.info('Nothing to compact')
            return None
        boundary_turn, boundary_part = boundary
        previous, previous_turn, previous_part = turns.compaction(base)
        if previous and (previous_turn, previous_part) >= boundary:
            if not auto:
                self.ui.info('Nothing to compact')
            return None
        start_turn = previous_turn if previous else 0
        start_part = previous_part if previous else 0
        msgs = turns.provider_messages_between(
            base, start_turn, start_part, boundary_turn, boundary_part)
        if not msgs:
            if not auto:
                self.ui.info('Nothing to compact')
            return None
        context_before = self._context_tokens()
        tokens_summarized = max(
            1, sum(len(m.get('content') or '') for m in msgs) // 4)
        rounds = self._compact_rounds(base)
        start = (start_turn, start_part)
        rounds_summarized = sum(
            1 for value in rounds if start <= value < boundary)
        self._compaction_seq = getattr(self, '_compaction_seq', 0) + 1
        compaction_index = self._compaction_seq
        if self._has_observers():
            turn = self.current_session.open_turn()
            self._emit({
                'type': 'compaction_before',
                'compaction_index': compaction_index,
                'turn': turn.get('index', 0) if turn else 0,
                'round': getattr(self, '_request_round', 0),
                'boundary_turn': boundary_turn,
                'boundary_part': boundary_part,
                'context_before': context_before,
                'rounds_summarized': rounds_summarized,
                'tokens_summarized': tokens_summarized,
            })
        summary = self._summarize(msgs, previous=previous)
        if summary is None:
            return None
        usage = getattr(self, '_last_summary_usage', None)
        record = self.current_session.set_compaction(
            summary, boundary_turn, boundary_part,
            auto=auto,
            reason='threshold' if auto else 'manual',
            usage=usage,
            context_before=context_before,
            rounds_summarized=rounds_summarized,
            tokens_summarized=tokens_summarized,
            compaction_index=compaction_index)
        record['context_after'] = self._context_tokens()
        if self._has_observers():
            event = dict(record)
            event['type'] = 'compaction'
            turn = self.current_session.open_turn()
            event['turn'] = turn.get('index', 0) if turn else 0
            event['round'] = getattr(self, '_request_round', 0)
            self._emit(event)
        try:
            header = (f'# Compaction summary: '
                      f'{self.current_session.session_name}\n\n'
                      f'- Compact from turn: {boundary_turn}\n')
            if boundary_part:
                header += f'- Compact from part: {boundary_part}\n'
            header += f'- Version: {self.current_session.version or "-"}\n\n'
            self.sessions.write_summary(
                self.current_session.session_name, header + summary)
        except OSError:
            pass
        if not auto:
            n, chars = self._context_size()
            self.ui.info(f'Compacted - context now {n} messages '
                         f'({self._human_chars(chars)})')
            self.ui.info('--- earlier conversation ---')
            self.ui.info(summary)
        self.session_auto_save()
        return record

    def _context_size(self) -> tuple[int, int]:
        msgs = self._provider_messages()
        chars = sum(len(m.get('content') or '') for m in msgs)
        return len(msgs), chars

    def _context_tokens(self, usage: dict | None = None) -> int:
        if isinstance(usage, dict):
            context = usage.get('context_tokens')
            if isinstance(context, int) and context > 0:
                return context
            prompt = usage.get('prompt_tokens')
            if isinstance(prompt, int) and prompt > 0:
                return prompt
        msgs = self._provider_messages()
        chars = sum(len(m.get('content') or '') for m in msgs)
        return max(1, chars // 4)

    def _usage_counts(self, usage: dict | None = None) -> dict:
        counts: dict = {}
        if isinstance(usage, dict):
            prompt = usage.get('prompt_tokens')
            if isinstance(prompt, int) and prompt > 0:
                counts['in'] = prompt
            completion = usage.get('completion_tokens')
            if isinstance(completion, int) and completion > 0:
                counts['out'] = completion
            details = usage.get('completion_tokens_details') or {}
            thinking = details.get('reasoning_tokens')
            if not isinstance(thinking, int):
                thinking = usage.get('reasoning_tokens')
            if isinstance(thinking, int) and thinking > 0:
                counts['thinking'] = thinking
        if isinstance(usage, dict):
            total = usage.get('total_tokens')
            if not isinstance(total, int) or total <= 0:
                total = ((usage.get('prompt_tokens') or 0)
                         + (usage.get('completion_tokens') or 0))
            if total:
                counts['total'] = total
        counts['context'] = self._context_tokens(usage)
        return counts

    def turn_usage(self, turn: dict | None = None) -> dict:
        target = turn or self.current_session.open_turn()
        if target is None:
            turns = self.current_session.turns
            target = turns[-1] if turns else {}
        usage = target.get('usage') if isinstance(target, dict) else None
        return dict(usage) if isinstance(usage, dict) else {}

    def session_usage(self) -> dict:
        totals = {'prompt_tokens': 0, 'completion_tokens': 0,
                  'reasoning_tokens': 0, 'total_tokens': 0, 'requests': 0}
        for turn in self.current_session.turns:
            usage = turn.get('usage') if isinstance(turn, dict) else None
            if not isinstance(usage, dict):
                continue
            for key in totals:
                value = usage.get(key)
                if isinstance(value, int) and value > 0:
                    totals[key] += value
        return totals

    def context_report(self) -> dict:
        messages, chars = self._context_size()
        usage = self.turn_usage()
        return {
            'messages': messages,
            'chars': chars,
            'tokens': self._context_tokens(usage),
            'window': self._context_window(),
            'turn': usage,
            'session': self.session_usage(),
        }

    def _tree_tokens(self, usage: dict | None = None) -> int:
        total = 0
        if isinstance(usage, dict):
            total += int(usage.get('total_tokens') or 0)
        run = getattr(self, 'current_run', None)
        if run is not None:
            for child in self.runs.children(run.id):
                total += int(self.runs.rollup(child.id).get('total_tokens') or 0)
        return total

    def _human_chars(self, n: int) -> str:
        if n >= 1_000_000:
            return f'{n / 1_000_000:.1f}M'
        if n >= 1_000:
            return f'{n / 1_000:.1f}k'
        return str(n)

    def preview_session(self, name: str, session=None):
        s = session if session is not None else self.sessions.read(name)
        if s is None:
            return None
        counts: dict[str, int] = {}
        tools: set[str] = set()
        for turn in s.turns:
            for part in turn.get('parts') or []:
                kind = part.get('type', '?')
                counts[kind] = counts.get(kind, 0) + 1
                if kind == 'tool' and part.get('name'):
                    tools.add(part['name'])
        self.ui.info(f'  {s.session_name} - {len(s.turns)} turns')
        self.ui.info(f'    created {s.created_at} · updated {s.updated_at}')
        title = s.derived_title()
        if title:
            self.ui.info(f'    title: {title}')
        self.ui.info(f'    outcome: {s.derived_outcome()} · idle {s.derived_idle_at()}')
        self.ui.info('    parts: ' + ' · '.join(f'{k} {v}' for k, v in counts.items()))
        if tools:
            self.ui.info('    tools: ' + ', '.join(sorted(tools)))
        if s.parent_id:
            self.ui.info(f'    parent: {s.parent_id}')
        if s.sub_sessions:
            self.ui.info('    sub-sessions: ' + ', '.join(s.sub_sessions))
        return s
