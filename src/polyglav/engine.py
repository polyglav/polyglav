import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import Config
from .runs import Run, RunRegistry
from .sessions.manager import SessionManager, coded_session_name
from .sessions import turns
from .commands.registry import CommandRegistry
from .commands.builtins import register_builtins
from .plugins.manager import PluginManager
from .ui import BufferUI, NullUI, ReplUI, SubRunUI


@dataclass
class TurnResult:
    content: str | None = None
    thinking: str | None = None
    tool_calls: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duration: float = 0.0
    usage: dict | None = None
    model: str = ''
    provider: str = ''
    session: str = ''
    status: str = 'ok'
    run_id: int | None = None

    def to_dict(self) -> dict:
        return {
            'content': self.content,
            'thinking': self.thinking,
            'tool_calls': self.tool_calls,
            'errors': self.errors,
            'duration': self.duration,
            'usage': self.usage,
            'model': self.model,
            'provider': self.provider,
            'session': self.session,
            'status': self.status,
            'run_id': self.run_id,
        }


@dataclass
class TeamRunResult:
    name: str = ''
    stages: list = field(default_factory=list)
    content: str | None = None
    memory: str = ''
    status: str = 'ok'
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'stages': [r.to_dict() for r in self.stages],
            'content': self.content,
            'memory': self.memory,
            'status': self.status,
            'errors': self.errors,
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


def _review_passed(content: str | None, marker: str) -> bool:
    if not content:
        return False
    return f'{marker} PASS'.lower() in content.lower()


def _stage_errors(role: str, result: TurnResult) -> list:
    if result.errors:
        return list(result.errors)
    status = result.status or 'error'
    detail = f'stage "{role}" ended with status "{status}"'
    if result.session:
        detail += f' (session {result.session})'
    return [{'code': status, 'message': detail + ' - see the sub-session log'}]


def _resolver_takes_policy(fn: Callable) -> bool:
    try:
        import inspect
        return '_permissions' in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


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
        self._pending_handoff = None
        self._pending_focus = None
        self._provider_error = None
        self._ui = ui
        self._sub_run = False
        self._denied_streak = 0
        self._unattended = bool(config.get('unattended'))
        self._ask_ui = ui if isinstance(ui, ReplUI) else None
        if self._unattended:
            self._ask_ui = None
        self._caller = None
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
        self.sessions = SessionManager(sessions_dir)
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

    def _is_unattended(self) -> bool:
        return bool(getattr(self, '_unattended',
                            self.config.get('unattended', False)))

    def set_unattended(self, enabled: bool):
        self._unattended = bool(enabled)
        if enabled:
            self._ask_ui = None
        else:
            self._ask_ui = self._ui if isinstance(self._ui, ReplUI) else None

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
    def asks(self):
        if getattr(self, '_asks', None) is None:
            from .asks import AskStore
            self._asks = AskStore(self.config.local_path.parent / 'asks.json')
        return self._asks

    @property
    def providers(self):
        if getattr(self, '_providers', None) is None:
            from .providers.registry import ProviderRegistry
            self._providers = ProviderRegistry()
        return self._providers

    @property
    def roles(self):
        if getattr(self, '_roles', None) is None:
            from .roles import RoleRegistry
            self._roles = RoleRegistry(
                local_path=self.config.local_path.parent / 'roles.json')
            self._plugin_manager.register_roles(self._roles)
        return self._roles

    @property
    def teams(self):
        if getattr(self, '_teams', None) is None:
            from .teams import TeamRegistry
            self._teams = TeamRegistry(
                local_path=self.config.local_path.parent / 'teams.json')
            self._plugin_manager.register_teams(self._teams)
        return self._teams

    @property
    def skills(self):
        if getattr(self, '_skills', None) is None:
            from .skills import SkillRegistry
            self._skills = SkillRegistry(
                local_dir=self.config.local_path.parent / 'skills')
            self._plugin_manager.register_skills(self._skills)
        return self._skills

    def bind_root_agent(self, name: str) -> bool:
        name = str(name or '').strip()
        if not name:
            return False
        agent_role = self.roles.find(name)
        if agent_role is None:
            return False
        self.role = name
        self.current_session.role = name
        self.current_run.role = name
        if self.config.origin('system_prompt') == 'default':
            prompt = agent_role.system_prompt
            if agent_role.skills:
                from .skills import skills_section
                section = skills_section(self.skills, agent_role.skills)
                if section:
                    if prompt.strip():
                        prompt = prompt.rstrip() + '\n\n' + section
                    else:
                        prompt = section
            if prompt:
                self.config.apply('system_prompt', prompt)
        if agent_role.model and self.config.origin('model') == 'default':
            self.config.apply('model', agent_role.model)
            self._reinit_provider()
        if (agent_role.tool_permission
                and self.config.origin('tool_permission') == 'default'):
            permissions = dict(self.config.get('tool_permission') or {})
            permissions.update(agent_role.tool_permission)
            self.config.apply('tool_permission', permissions)
        if (agent_role.grant_permission
                and self.config.origin('grant_permission') == 'default'):
            self.config.apply('grant_permission',
                              dict(agent_role.grant_permission))
        if (agent_role.ask_policy
                and self.config.origin('ask_policy') == 'default'):
            policy = dict(self.config.get('ask_policy') or {})
            policy.update(agent_role.ask_policy)
            self.config.apply('ask_policy', policy)
        return True

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
        if self._is_unattended():
            return False
        if isinstance(self.ui, ReplUI):
            try:
                ok = self.ui.confirm('model', f'Approve model "{provider}/{model}"')
            except KeyboardInterrupt:
                return False
            if ok:
                self.models.put(provider, model)
                return True
            return False
        return False

    def _reinit_provider(self):
        provider_name = self.config.get('provider', 'ollama')
        factory, resolved, merged = self._resolve_provider_factory(
            provider_name, self.config.get('base_url'))
        if factory is None:
            return
        if resolved != provider_name:
            self.config.apply('provider', resolved)
            provider_name = resolved

        base_url = self.config.get('base_url')
        if not base_url:
            base_url = self.providers.base_url_for(provider_name)
        model = self.config.get('model')

        from .providers.registry import resolve_model_ref
        unfolded = resolve_model_ref(model, self._merged_providers()) if model else None
        if unfolded is not None:
            provider_name, base_url, model = unfolded
            if not self.providers.api_key_for(provider_name):
                self.ui.info(f'Provider "{provider_name}" has no API key - '
                             f'run /connect {provider_name}')
            if not self._ensure_model_approved(provider_name, model):
                self._provider_error = (
                    f'Model "{provider_name}/{model}" is not approved. Approve it '
                    f'with /model {provider_name}/{model}, --model, or --approve-model.')
                self.ui.info(f'[Error] {self._provider_error}')
                self.config.apply('provider', provider_name)
                self.config.apply('base_url', base_url)
                self.config.apply('model', model)
                return
            self.config.apply('provider', provider_name)
            self.config.apply('base_url', base_url)
            self.config.apply('model', model)
            factory, _, merged = self._resolve_provider_factory(provider_name, base_url)
            if factory is None:
                return
        elif getattr(self, 'approve_models', False) and model:
            self.models.put(provider_name, model)
        self._provider_error = None

        if factory.DEFAULT_BASE_URL and base_url:
            for other in merged.values():
                if other is not factory and other.DEFAULT_BASE_URL and base_url == other.DEFAULT_BASE_URL:
                    base_url = factory.DEFAULT_BASE_URL
                    break
        if factory.DEFAULT_MODEL and model:
            for other in merged.values():
                if other is not factory and other.DEFAULT_MODEL and model == other.DEFAULT_MODEL:
                    model = factory.DEFAULT_MODEL
                    break
        if base_url != self.config.get('base_url'):
            self.config.apply('base_url', base_url)
        if model != self.config.get('model'):
            self.config.apply('model', model)

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
        provider = provider or self.config.get('provider')
        base_url = self.config.get('base_url') if base_url is None else base_url
        if not base_url:
            base_url = self.providers.base_url_for(provider)
        model = model or self.config.get('model')
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
        provider = provider or self.config.get('provider')
        base_url = self.config.get('base_url') if base_url is None else base_url
        if not base_url:
            base_url = self.providers.base_url_for(provider)
        model = self.config.get('model') if model is None else model
        if api_key is None:
            api_key = self.providers.api_key_for(provider)
        factory, _, _ = self._resolve_provider_factory(provider, base_url)
        if factory is None:
            return [], f'No provider registered for "{provider}"'
        probe = factory(base_url=base_url, api_key=api_key, model=model)
        return probe._fetch_models()

    def session_auto_save(self):
        if self.current_session and self.current_session.turns:
            self.sessions.save(
                self.current_session,
                tool_max_chars=self.config.get('session_tool_max_chars', 0),
                noise_tools=self.config.get('noise_tools', []),
            )

    def load_or_create_session(self, name: str | None = None):
        if name and self.sessions.read(name) is not None:
            self.current_session = self.sessions.load(name)
        elif name:
            self.current_session = self.sessions.create(name, role=self.role)
        else:
            self.current_session = self.sessions.create(role=self.role)
        self.current_run.session = self.current_session.session_name
        self.current_run.session_id = self.current_session.session_id
        self._bind_provider_session()
        return self.current_session

    def _grant(self) -> dict:
        ceiling = getattr(self, '_grant_ceiling', None)
        if isinstance(ceiling, dict):
            return dict(ceiling)
        grant = self.config.get('grant_permission')
        if isinstance(grant, dict) and grant:
            return dict(grant)
        return self._self_permissions()

    def _self_permissions(self) -> dict:
        from .modes import merge_policy, mode_name
        return dict(merge_policy(self.config, mode_name(self.config))[0])

    def grant_permission(self, permission: str, permission_key: str,
                         scope: str = 'once', origin: str = 'supervisor') -> bool:
        policy = getattr(self, '_tool_policy', None)
        if policy is None:
            return False
        registry = getattr(self, '_tool_registry', None)
        name = ''
        if registry is not None and registry.is_registered(permission):
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
        agent_role = self.roles.find(role_name)
        if agent_role is None:
            raise ValueError(f'Unknown role: {role_name}')
        sub_config = Config(path=str(self.config.local_path.parent.parent))
        from .skills import skills_section
        system_prompt = agent_role.system_prompt
        names = list(agent_role.skills or [])
        for name in (skills or []):
            if name and name not in names:
                names.append(name)
        if names:
            section = skills_section(self.skills, names)
            if section:
                if system_prompt.strip():
                    system_prompt = system_prompt.rstrip() + '\n\n' + section
                else:
                    system_prompt = section
        from . import memory as memory_store
        worktree = self.config.local_path.parent.parent
        if memory_store.memory_enabled(sub_config, 'role'):
            text = memory_store.read_memory(worktree, 'role', role_name)
            section = memory_store.memory_section(text, self.config)
            if section:
                if system_prompt.strip():
                    system_prompt = system_prompt.rstrip() + '\n\n' + section
                else:
                    system_prompt = section
        sub_config.apply('system_prompt', system_prompt)
        if agent_role.model:
            ref = self.unfold_ref(agent_role.model)
            if ref is not None:
                t_provider, t_base_url, t_model = ref
                sub_config.apply('provider', t_provider)
                sub_config.apply('base_url', t_base_url)
                sub_config.apply('model', t_model)
            else:
                sub_config.apply('model', agent_role.model)
        from .roles import resolve_permissions, resolve_grant_ceiling
        parent_self = self._self_permissions()
        parent_grant = self._grant()
        permissions = resolve_permissions(
            parent_self, parent_grant, agent_role.tool_permission)
        sub_config.apply('tool_permission', permissions)
        requested = agent_role.tool_permission or {}
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
        sub_config.apply('mode', mode or str(self.config.get('mode') or 'read'))
        sub_config.apply('unattended', self._is_unattended())
        if agent_role.ask_policy:
            ask_policy = dict(self.config.get('ask_policy') or {})
            ask_policy.update(agent_role.ask_policy)
            sub_config.apply('ask_policy', ask_policy)
        if provider is None and not agent_role.model:
            provider = self.provider
        sub = Engine(sub_config, ui=ui,
                     plugin_manager=self._plugin_manager, provider=provider,
                     runs=self.runs, parent_run=self.current_run.id, run=run)
        if ui is None:
            max_lines = int(self.config.get('run_buffer_max_lines', 0) or 0)
            verbosity = str(
                self.config.get('subrun_verbosity', 'quiet') or 'quiet').lower()
            if verbosity == 'summary':
                sub._ui = SubRunUI(sub.current_run, self.ui,
                                   max_lines=max_lines)
            elif verbosity == 'full':
                sub._ui = SubRunUI(sub.current_run, self.ui,
                                   max_lines=max_lines, forward_all=True)
            else:
                sub._ui = BufferUI(sub.current_run, max_lines=max_lines)
        sub.role = role_name
        sub.current_run.role = role_name
        sub.current_run.task = task
        sub._sub_run = True
        sub._caller = self
        sub._ask_ui = getattr(self, '_ask_ui', None)
        sub._grant_ceiling = resolve_grant_ceiling(
            parent_self, parent_grant, agent_role.grant_permission, permissions)
        sub._team_depth = getattr(self, '_team_depth', 0)
        sub._team_stack = list(getattr(self, '_team_stack', []))
        if session_name:
            sub.load_or_create_session(session_name)
        else:
            sub.load_or_create_session(_sub_session_name(
                self.current_session.session_name, self.sessions.sessions_dir))
        if link_parent:
            sub.current_session.parent_id = self.current_session.session_name
        self.runs.set_engine(sub.current_run.id, sub)
        return sub

    def run_engine(self, run: Run, ui=None) -> 'Engine':
        if run.id == self.current_run.id:
            return self
        if run.role and self.roles.find(run.role) is not None:
            sub = self._new_sub_engine(
                run.role, session_name=run.session, ui=ui, link_parent=False,
                run=run)
        else:
            sub = Engine(self.config, ui=ui if ui is not None else NullUI(),
                         plugin_manager=self._plugin_manager,
                         provider=self.provider, runs=self.runs, run=run)
            sub.load_or_create_session(run.session)
            sub._sub_run = True
            sub._caller = self
            sub._ask_ui = getattr(self, '_ask_ui', None)
        sub.role = run.role
        sub.current_run.role = run.role
        sub.current_session.role = run.role
        sub.current_session.parent_id = ''
        self.runs.set_engine(run.id, sub)
        self.runs.reactivate(run.id)
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
            return run, run.session if run is not None else ''
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
        agent_role = self.roles.find(role_name)
        if agent_role is None:
            raise ValueError(f'Unknown role: {role_name}')
        if agent_role.model:
            ref = self.unfold_ref(agent_role.model)
            provider, _, model = ref if ref else (
                self.config.get('provider'), None, agent_role.model)
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
        if run is not None:
            self.runs.reactivate(run.id)
        if ctx == 'compact':
            sub.compact_session()
        label = role_name
        stack = list(getattr(self, '_team_stack', []))
        if stack:
            label = f'{stack[-1]}: {role_name}'
        self.ui.status_begin(f'{label}...')
        try:
            result = sub.chat(task)
        except Exception:
            self.ui.status_end()
            self.runs.finish(sub.current_run.id, 'error')
            raise
        self.ui.status_end(self._run_stats(result))
        status = 'done' if result.status in ('ok', 'truncated') else 'error'
        self.runs.finish(sub.current_run.id, status)
        if result.session and result.session not in self.current_session.sub_sessions:
            self.current_session.sub_sessions.append(result.session)
            self.session_auto_save()
        self._update_role_memory(role_name, result.session)
        return result

    def _run_stats(self, result: TurnResult) -> str:
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
            parts.append(f'{int(total):,} tokens')
        return f'({", ".join(parts)})'

    def _update_role_memory(self, role: str, session_name: str):
        if not role or not session_name:
            return
        from . import memory as memory_store
        worktree = self.config.local_path.parent.parent
        if not memory_store.memory_enabled(self.config, 'role'):
            return
        session = self.sessions.read(session_name)
        if session is None or not session.turns:
            return
        prior = memory_store.read_memory(worktree, 'role', role)
        messages = []
        if prior:
            messages.append({'role': 'system',
                             'content': f'Previous role memory:\n{prior}'})
        messages += turns.provider_messages(session.turns)
        if not messages:
            return
        try:
            summary = self._summarize(messages)
        except Exception:
            summary = None
        if not isinstance(summary, str) or not summary:
            return
        memory_store.write_memory(worktree, 'role', role, summary)

    def memorize(self, scope: str = 'role', name: str = '',
                 session=None) -> str:
        from . import memory as memory_store
        scope = str(scope or 'role').strip().lower()
        if scope not in memory_store.SCOPES:
            return f'Error: scope must be one of {", ".join(memory_store.SCOPES)}'
        name = str(name or '').strip()
        if not name:
            if scope == 'role':
                name = self.role or self.current_session.role or \
                    self.current_session.session_name
            else:
                return f'Error: /memorize {scope} needs a name'
        if not memory_store.memory_enabled(self.config, scope):
            return f'Memory for scope "{scope}" is disabled'
        worktree = self.config.local_path.parent.parent
        prior = memory_store.read_memory(worktree, scope, name)
        messages = []
        if prior:
            messages.append({'role': 'system',
                             'content': f'Previous {scope} memory:\n{prior}'})
        messages += turns.provider_messages((session or self.current_session).turns)
        if not messages:
            return 'Nothing to memorize'
        summary = self._summarize(messages)
        if not isinstance(summary, str) or not summary:
            return 'Memory not updated'
        path = memory_store.write_memory(worktree, scope, name, summary)
        return f'Wrote {scope} memory: {path}'

    def _build_stage_brief(self, team, task: str, results: list,
                           index: int, memory: str,
                           prior_cap: int = 4000) -> str:
        parts = [f'Team: {team.name}'
                 + (f' ({team.description})' if team.description else ''),
                 f'Original task:\n{task}']
        for j, res in enumerate(results[:index], 1):
            content = (res.content or '').strip()
            if not content:
                content = f'(no final text from {res.session or "stage"})'
            if len(content) > prior_cap:
                content = content[:prior_cap].rsplit(' ', 1)[0] + '\n... (truncated)'
            parts.append(f'## Stage {j} result ({res.session or "stage"}):\n{content}')
        stage = team.stages[index]
        if index > 0 and team.stages[index - 1].handoff_note:
            parts.append(f'Stage {index + 1} handoff from {team.stages[index - 1].role}: '
                         f'{team.stages[index - 1].handoff_note}')
        if memory:
            parts.append(f'## Team memory\n{memory}')
        hint = stage.task_hint or 'Complete this stage of the task.'
        parts.append(f'Your stage ({stage.role}):\n{hint}')
        parts.append(f'You are stage {index + 1} of team "{team.name}". Do this '
                     f"stage's work directly and do not call the team tool for "
                     f'"{team.name}".')
        return '\n\n'.join(parts)

    def _team_memory_summary(self, team, results: list, prior: str) -> str:
        messages = []
        if prior:
            messages.append({'role': 'system',
                             'content': f'Previous team memory:\n{prior}'})
        for res in results:
            session = self.sessions.read(res.session) if res.session else None
            if session is not None:
                messages += turns.provider_messages(session.turns)
        if not messages:
            return ''
        try:
            summary = self._summarize(messages)
        except Exception:
            summary = None
        if summary:
            return str(summary).strip()
        lines = [f'Team {team.name} run:']
        for i, res in enumerate(results, 1):
            content = (res.content or '').strip().replace('\n', ' ')
            part = f'Stage {i} ({res.session or "?"}): {res.status}'
            if content:
                part += f' - {content[:200]}'
            else:
                msg = ''
                for e in res.errors or []:
                    if isinstance(e, dict) and e.get('message'):
                        msg = str(e['message'])
                        break
                if msg:
                    part += f' - Error: {msg[:200]}'
            lines.append(part)
        return '\n'.join(lines)[:1500]

    def run_team(self, team, task: str, skills: list | None = None,
                 resume: str = '', context: str = 'continue') -> TeamRunResult:
        depth = getattr(self, '_team_depth', 0)
        max_depth = int(self.config.get('max_team_depth', 2) or 0)
        stack = list(getattr(self, '_team_stack', []))
        if team.name in stack:
            return TeamRunResult(
                name=team.name, status='error',
                errors=[{'code': 'team_cycle', 'message':
                         f'Team cycle detected: {" -> ".join(stack + [team.name])}. '
                         'This run is already a stage of that team; do the '
                         'stage work directly and do not call the team tool '
                         'for it again.'}])
        if max_depth and depth >= max_depth:
            return TeamRunResult(
                name=team.name, status='error',
                errors=[{'code': 'team_depth', 'message':
                         f'Team nesting limit reached ({max_depth}): {team.name}'}])
        self._team_stack = stack + [team.name]
        self._team_depth = depth + 1
        try:
            return self._run_team_stages(
                team, task, skills=skills, resume=resume, context=context)
        finally:
            self._team_stack = stack
            self._team_depth = depth

    def _run_team_stage(self, team, stage, brief: str, skills: list | None,
                        resume: str = '', context: str = 'continue') -> TurnResult:
        mode = stage.mode or str(self.config.get('mode') or 'read')
        stage_skills = list(skills or [])
        for name in (stage.skills or []):
            if name and name not in stage_skills:
                stage_skills.append(name)
        if stage is team.stages[0] and resume:
            return self.run_subagent(stage.role, brief, mode=mode,
                                     skills=stage_skills, resume=resume,
                                     context=context)
        return self.run_subagent(stage.role, brief, mode=mode,
                                 skills=stage_skills)

    def _build_iteration_brief(self, team, task: str, memory: str, stage,
                               prior: list, iteration: int,
                               review: str = '') -> str:
        parts = [f'Team: {team.name}'
                 + (f' ({team.description})' if team.description else ''),
                 f'Original task:\n{task}']
        if iteration > 1:
            parts.append(f'Review loop iteration {iteration}.')
        if review:
            parts.append(f'## Findings from the previous review\n{review}')
        for j, res in enumerate(prior, 1):
            content = (res.content or '').strip()
            if not content:
                content = f'(no final text from {res.session or "stage"})'
            if len(content) > 4000:
                content = content[:4000].rsplit(' ', 1)[0] + '\n... (truncated)'
            parts.append(f'## Iteration result {j} '
                         f'({res.session or "stage"}):\n{content}')
        if memory:
            parts.append(f'## Team memory\n{memory}')
        hint = stage.task_hint or 'Complete this stage of the task.'
        parts.append(f'Your stage ({stage.role}):\n{hint}')
        parts.append(f'You are a stage of team "{team.name}". Do this stage\'s '
                     f'work directly and do not call the team tool for '
                     f'"{team.name}".')
        return '\n\n'.join(parts)

    def _team_loop_plan(self, team):
        loop = dict(team.loop or {})
        if not loop:
            return None
        names = [stage.role for stage in team.stages]

        def resolve(value):
            if isinstance(value, int):
                return value
            if value is None:
                return None
            try:
                return names.index(str(value))
            except ValueError:
                return None

        frm = resolve(loop.get('from'))
        until = resolve(loop.get('until'))
        if frm is None or until is None or frm > until:
            return None
        max_iterations = max(1, int(loop.get('max_iterations', 3) or 3))
        marker = str(loop.get('verdict') or 'VERDICT:')
        return frm, until, max_iterations, marker

    def _run_team_loop(self, team, task: str, skills: list | None,
                       memory: str, plan, stages: list,
                       resume: str = '', context: str = 'continue') -> tuple[str, list]:
        frm, until, max_iterations, marker = plan
        for i in range(0, frm):
            stage = team.stages[i]
            brief = self._build_stage_brief(team, task, stages, i, memory)
            res = self._run_team_stage(
                team, stage, brief, skills, resume, context)
            stages.append(res)
            if res.status not in ('ok', 'truncated'):
                return 'error', _stage_errors(stage.role, res)
        iterations = 0
        last_review = ''
        block: list[TurnResult] = []
        while True:
            iterations += 1
            block = []
            for i in range(frm, until + 1):
                stage = team.stages[i]
                review = last_review if i == frm else ''
                brief = self._build_iteration_brief(
                    team, task, memory, stage, block, iterations, review)
                res = self._run_team_stage(
                    team, stage, brief, skills, resume, context)
                stages.append(res)
                block.append(res)
                if res.status not in ('ok', 'truncated'):
                    return 'error', _stage_errors(stage.role, res)
            last_review = (block[-1].content or '') if block else ''
            if _review_passed(last_review, marker):
                break
            if iterations >= max_iterations:
                break
        for i in range(until + 1, len(team.stages)):
            stage = team.stages[i]
            brief = self._build_iteration_brief(
                team, task, memory, stage, block, iterations)
            res = self._run_team_stage(
                team, stage, brief, skills, resume, context)
            stages.append(res)
            if res.status not in ('ok', 'truncated'):
                return 'error', _stage_errors(stage.role, res)
        return 'ok', []

    def _run_team_stages(self, team, task: str, skills: list | None = None,
                         resume: str = '', context: str = 'continue') -> TeamRunResult:
        from .teams import read_team_memory, write_team_memory
        for stage in team.stages:
            agent_role = self.roles.find(stage.role)
            if agent_role is None or not agent_role.model:
                continue
            ref = self.unfold_ref(agent_role.model)
            provider, _, model = ref if ref else (
                self.config.get('provider'), None, agent_role.model)
            if not self._ensure_model_approved(provider, model):
                return TeamRunResult(
                    name=team.name, status='error',
                    errors=[{'code': '', 'message':
                        f'Stage "{stage.role}" uses unapproved model "{model}" - '
                        'approve it first (/model, --approve-model, or /connect)'}])
        worktree = self.config.local_path.parent.parent
        memory = read_team_memory(worktree, team.name)
        stages: list[TurnResult] = []
        errors: list = []
        status = 'ok'
        try:
            plan = self._team_loop_plan(team)
            if plan is None:
                for i, stage in enumerate(team.stages):
                    brief = self._build_stage_brief(team, task, stages, i, memory)
                    res = self._run_team_stage(team, stage, brief, skills,
                                               resume, context)
                    stages.append(res)
                    if res.status not in ('ok', 'truncated'):
                        status = 'error'
                        errors.extend(_stage_errors(stage.role, res))
                        break
            else:
                status, errors = self._run_team_loop(
                    team, task, skills, memory, plan, stages, resume, context)
        except ValueError as e:
            status = 'error'
            errors.append({'code': '', 'message': str(e)})
        summary = self._team_memory_summary(team, stages, memory)
        memory_path = ''
        if summary:
            memory_path = str(write_team_memory(worktree, team.name, summary))
        content = None
        if stages:
            last = stages[-1]
            if last.content:
                content = last.content
        return TeamRunResult(
            name=team.name,
            stages=stages,
            content=content,
            memory=memory_path,
            status=status,
            errors=errors,
        )

    def _turn_meta(self) -> dict:
        return {
            'model': self.config.get('model'),
            'provider': self.config.get('provider'),
            'mode': self.config.get('mode'),
            'reasoning': self.config.get('reasoning'),
        }

    def chat(self, text: str) -> TurnResult:
        if getattr(self, '_provider_error', None):
            return TurnResult(status='error',
                              errors=[{'code': '', 'message': self._provider_error}],
                              session=self.current_session.session_name)
        now = datetime.now(timezone.utc)
        self.current_session.add_user(
            text, timestamp=now.isoformat(timespec='seconds'), **self._turn_meta()
        )
        self.session_auto_save()

        if self.config.get('tool_calling'):
            return self._agent_loop()
        if self.config.get('web_search'):
            context = self._perform_search(text, silent=True)
            if context:
                self.current_session.add_system(context)
            else:
                self.ui.info('(Skipping AI - no search results)')
                return TurnResult(status='empty', session=self.current_session.session_name)
        return self._agent_loop()

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

    def _agent_loop(self, seed_tool: tuple[str, dict] | None = None) -> TurnResult:
        self._pending_handoff = None
        self._denied_streak = 0
        if self.current_session.open_turn() is None:
            self.current_session.start_turn(**self._turn_meta())
        tools_schema = self._init_tooling()
        turn_start = datetime.now(timezone.utc)
        usage = None
        status = 'ok'
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
                auto_continue = self.config.get('auto_continue', True)
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
                                                self.ui.token(before)
                                            s_thinking += marker
                                            feed_thinking(marker)
                                            token = token[idx + len(marker):]
                                            in_thinking = True
                                        else:
                                            end_thinking()
                                            s_content += token
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
                            elif t == 'tool_calls':
                                tool_calls_detected = True
                                end_thinking()
                                executed_tool_calls += self._execute_tool_calls(
                                    event['tool_calls'], s_thinking or None)
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
                                usage = event.get('usage') or usage
                                reason = event.get('reason', '')
                                end_thinking()
                                break
                    except KeyboardInterrupt:
                        end_thinking()
                        content += s_content
                        thinking += s_thinking
                        self.ui.info('(cancelled)')
                        status = 'cancelled'
                        aborted = True
                    except Exception as e:
                        end_thinking()
                        content += s_content
                        thinking += s_thinking
                        self.current_session.add_error(0, f'Agent loop failed: {e}')
                        self.ui.error(0, str(e))
                        status = 'error'
                        aborted = True
                    if aborted:
                        break
                    if tool_calls_detected:
                        break
                    content += s_content
                    thinking += s_thinking
                    if got_done:
                        if reason == 'length':
                            if content and auto_continue and consumes < max_continues:
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
                if aborted or not tool_calls_detected or self._pending_handoff:
                    break
        except KeyboardInterrupt:
            self.ui.info('(cancelled)')
            status = 'cancelled'
        finally:
            if content or thinking:
                end = datetime.now(timezone.utc)
                duration = round((end - turn_start).total_seconds(), 1)
                stamp = end.isoformat(timespec='seconds')
                self.current_session.add_thinking(thinking, stamp)
                if content:
                    self.current_session.add_text(content, stamp)
                self.ui.footer(duration, self._usage_counts(usage))
            self.current_session.end_turn(status)
            self.session_auto_save()

        duration = round((datetime.now(timezone.utc) - turn_start).total_seconds(), 1)
        return TurnResult(
            content=content or None,
            thinking=thinking or None,
            tool_calls=executed_tool_calls,
            errors=self.current_session.errors[err_base:],
            duration=duration,
            usage=usage,
            model=self.config.get('model'),
            provider=self.config.get('provider'),
            session=self.current_session.session_name,
            status=status,
            run_id=self.current_run.id,
        )

    def _execute_tool_calls(self, tcs: list[dict], thinking: str = '') -> list[dict]:
        self.current_session.add_thinking(thinking)
        executed: list[dict] = []
        for tc in tcs:
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
            part = self.current_session.add_tool(name, args)
            output = self._run_tool(name, args)
            if (self.config.get('tool_status_visible', True)
                    and self._tool_registry.echo_for(name) and output
                    and not self._tool_registry.is_note_result(name, output)
                    and not output.startswith(('[cancelled]', 'Error'))):
                if self._tool_registry.is_error_result(name, output):
                    self.ui.tool_error_result(output)
                else:
                    self.ui.tool_result(output)
            executed.append({'name': name, 'arguments': args})
            analysis = None
            if (self.config.get('tool_analysis')
                    and output and not output.startswith(('[cancelled]', 'Error'))):
                analysis = self._analyze_tool_result(name, output)
            turns.finish_tool(part, output, is_error=output.startswith('Error'),
                              analysis=analysis)
        return executed

    def _analyze_tool_result(self, name: str, output: str) -> str | None:
        sys_prompt = (
            "You write one-line insights for a session log. Given a tool name and its raw "
            "result, state in a single sentence what useful information the result provided - "
            "so a reader of the log can reconstruct the key insight without re-running the tool. "
            "Return only that sentence, nothing else."
        )
        try:
            result = self.provider.chat_nonstreaming(
                [
                    {'role': 'system', 'content': sys_prompt},
                    {'role': 'user', 'content': f'Tool: {name}\n\nResult:\n{output[:2000]}'},
                ],
                tools=None,
            )
        except Exception:
            return None
        content = result.get('content')
        if not isinstance(content, str):
            return None
        content = content.strip()
        return content or None

    def _perform_search(self, query: str, silent: bool = False) -> str | None:
        pm = getattr(self, '_plugin_manager', None)
        service = pm.service('search') if pm is not None else None
        if service is None:
            if not silent:
                self.ui.info('(web search unavailable - polyglav-core-web plugin not loaded)')
            return None

        num = self.config.get('search_results', 5)
        results = service.search(query, num)

        if not results:
            if not silent:
                self.ui.info('(no search results)')
            return None

        if not silent:
            self.ui.info('')
            self.ui.info(service.display(query, results))

        return service.context(query, results)

    def _init_tooling(self):
        if not self.config.get('tool_calling'):
            self._tool_registry = None
            self._tool_policy = None
            return None
        from .tools.registry import ToolRegistry
        from .tools.policy import ToolPolicy
        from .tools.delegate import register_delegate_tool
        from .tools.team import register_team_tool
        from .tools.ask import register_ask_tool
        from .tools.catalog import register_catalog_tool
        from .tools.handoff import register_handoff_tool
        from .modes import merge_policy, mode_name, read_keys
        mode = mode_name(self.config)
        self._tool_registry = ToolRegistry()
        register_delegate_tool(self._tool_registry, self)
        register_team_tool(self._tool_registry, self)
        register_ask_tool(self._tool_registry, self)
        register_catalog_tool(self._tool_registry, self)
        register_handoff_tool(self._tool_registry, self)
        plugin_manager = getattr(self, '_plugin_manager', None)
        if plugin_manager is not None:
            plugin_manager.register_tools(self._tool_registry)
        permissions, allow, deny = merge_policy(self.config, mode)
        resolvers = {}
        for n in self._tool_registry.names():
            fn = self._tool_registry.resolver_for(n)
            if fn is None:
                continue
            if _resolver_takes_policy(fn):
                fn = (lambda f: lambda args, f=f: f(args, _permissions=permissions))(fn)
            resolvers[n] = fn
        self._tool_policy = ToolPolicy(
            permissions=permissions,
            allow=allow,
            deny=deny,
            worktree=self.config.local_path.parent.parent,
            resolvers=resolvers,
            mode=mode,
            read_keys=read_keys(self.config),
        )
        return self._tool_schema()

    def _tool_schema(self):
        registry = getattr(self, '_tool_registry', None)
        policy = getattr(self, '_tool_policy', None)
        if registry is None or policy is None:
            return []
        allowed = {n for n in registry.names()
                   if policy.allowed(n, registry.permission_for(n))}
        return registry.schema_filtered(allowed)

    def _run_tool(self, name: str, args: dict, echo: bool = True) -> str:
        registry = self._tool_registry
        policy = self._tool_policy
        if not registry.is_registered(name):
            available = ', '.join(registry.primary_names())
            result = f'Error: unknown tool "{name}"'
            if available:
                result += f'. Available tools: {available}'
            if self.config.get('show_errors', True):
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
        if self.config.get('tool_status_visible', True):
            self._show_tool_status(name, args)
        result = registry.execute(name, args, config=self.config, echo=echo)
        if result.startswith('Error') and self.config.get('show_errors', True):
            self.ui.tool_error(result)
        elif (registry.is_note_result(name, result)
              and self.config.get('show_notes', True)):
            self.ui.tool_note(result)
        self._denied_streak = 0
        return result

    def _log_permission(self, name: str, action: str, decision: str,
                        path: str | None = None, **extra):
        self.current_session.add_permission(name, action, decision, path, **extra)

    def _confirm_tool(self, name: str, args: dict) -> bool:
        if self._is_unattended():
            return False
        key_arg = self._tool_registry.key_arg_for(name)
        label = name
        if key_arg and args.get(key_arg):
            value = str(args[key_arg])
            label = f'{name} {value[:80]}'
        params = self._tool_registry.params_str(name, args)
        if params and self.config.get('glyph_params', True):
            label = f'{label} [{params}]'
        return self.ui.confirm(name, label)

    def _show_tool_status(self, name, arguments):
        value, body = self._tool_registry.status_parts(name, arguments)
        activity = self._tool_registry.activity(name, arguments)
        if activity is not None and self.config.get('glyph_lines', True):
            glyph, verb, label, params = activity
            if params and self.config.get('glyph_params', True):
                label = f'{label} [{params}]'
            self.ui.activity(glyph, verb, label, body)
        else:
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
        summary, boundary = turns.compaction(self.current_session.turns)
        out = []
        if summary:
            out.append({
                'role': 'system',
                'content': 'Summary of earlier conversation:\n\n' + summary,
            })
        instructions = instructions_file_section(self.config)
        if instructions:
            out.append({'role': 'system', 'content': instructions})
        instruction = system_instruction(self.config)
        if instruction:
            out.append({'role': 'system', 'content': instruction})
        for turn in self.current_session.turns:
            if boundary and turn.get('index', 0) < boundary:
                continue
            out.extend(turns.turn_to_provider(turn))
        return out

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

    def _summarize(self, msgs: list[dict]) -> str | None:
        clean = self._clean_messages(msgs)
        prompt = (
            "Summarize the conversation up to this point into a concise summary that "
            "preserves key facts, decisions, tool findings, and open questions. "
            "The summary will be the only remaining record of the earlier conversation. "
            "Return only the summary text, nothing else."
        )
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
        return summary

    def compact_session(self):
        keep = max(0, int(self.config.get('compact_keep', 4)))
        base = list(self.current_session.turns)
        if base and turns.command_only(base[-1]):
            base = base[:-1]
        if not base:
            self.ui.info('Nothing to compact')
            return
        boundary = max(0, len(base) - keep) if keep else 0
        summarize = base[:boundary]
        if not summarize:
            self.ui.info('Nothing to compact')
            return
        summary = self._summarize(turns.provider_messages(summarize))
        if summary is None:
            return
        if boundary < len(base):
            compact_from = base[boundary]['index']
        else:
            compact_from = base[-1]['index'] + 1
        self.current_session.set_compaction(summary, compact_from)
        n, chars = self._context_size()
        self.ui.info(f'Compacted - context now {n} messages ({self._human_chars(chars)})')
        self.ui.info('--- earlier conversation ---')
        self.ui.info(summary)
        self.session_auto_save()

    def _context_size(self) -> tuple[int, int]:
        msgs = self._provider_messages()
        chars = sum(len(m.get('content') or '') for m in msgs)
        return len(msgs), chars

    def _context_tokens(self, usage: dict | None = None) -> int:
        if isinstance(usage, dict):
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
        counts['context'] = self._context_tokens(usage)
        return counts

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
        self.ui.info('    parts: ' + ' · '.join(f'{k} {v}' for k, v in counts.items()))
        if tools:
            self.ui.info('    tools: ' + ', '.join(sorted(tools)))
        if s.parent_id:
            self.ui.info(f'    parent: {s.parent_id}')
        if s.sub_sessions:
            self.ui.info('    sub-sessions: ' + ', '.join(s.sub_sessions))
        return s
