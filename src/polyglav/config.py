import copy
import json
from pathlib import Path


DEFAULT_CONFIG = {
    'access': {
        'read_tools': ['read', 'list', 'web', 'catalog', 'ask', 'delegate'],
    },
    'ask_min_question_chars': 8,
    'ask_policy': {
        'permission': 'auto',
        'direction': '',
    },
    'auto_continue_max': 2,
    'base_url': 'https://api.ollama.com',
    'compact_at': 170000,
    'compact_auto': True,
    'compact_before': 3,
    'compact_keep': 1,
    'context_window': 0,
    'cost.rates': {},
    'delegate_depth': 1,
    'grant_permission': {},
    'max_team_depth': 2,
    'max_tokens': 8192,
    'mode': 'read',
    'model': 'llama3.2',
    'modes': {
        'read': {
            'cap': 'read',
            'description': 'Assistance, chat, and planning tasks',
            'system_prompt': (
                'You are in read mode, which is for assistant, chat, and '
                'planning tasks. Investigate, cite sources, and write a plan '
                'when the task is large or long-running. Use plan_write when a '
                'durable plan helps and todo when a short checklist helps. Both '
                'are bookkeeping and do not modify the workspace. Do not edit '
                'the repository, run shell commands, commit, or call roles. Ask '
                'for write mode when the work needs tools, edits, commands, or '
                'roles.'
            ),
            'color': 'teal',
        },
        'write': {
            'cap': 'write',
            'description': ('Working tasks, tools, edits, commands, '
                            'roles, and teams'),
            'system_prompt': (
                'You are in write mode, which is for working tasks, accessing '
                'tools, and creating and calling roles and teams. Execute the '
                'plan, update the plan and todo as the work changes, and verify '
                'each step. When a plan exists, follow it. When the work reveals '
                'a better path, update the plan first, then continue.'
            ),
            'color': 'orange',
        },
    },
    'plan': {
        'dir': '.polyglav/plans',
    },
    'plugins': [
        'polyglav-core-anthropic',
        'polyglav-core-bookkeeping',
        'polyglav-core-dev',
        'polyglav-core-edit',
        'polyglav-core-exec',
        'polyglav-core-fs',
        'polyglav-core-git',
        'polyglav-core-groq',
        'polyglav-core-memory',
        'polyglav-core-ollama',
        'polyglav-core-onboarding',
        'polyglav-core-openai',
        'polyglav-core-opencode',
        'polyglav-core-providers',
        'polyglav-core-repl',
        'polyglav-core-roles',
        'polyglav-core-sessions',
        'polyglav-core-serve',
        'polyglav-core-skills',
        'polyglav-core-teams',
        'polyglav-core-web',
    ],
    'project_instructions': 'AGENTS.md',
    'reasoning': 'auto',
    'session.storage': 'json',
    'stream_retries': 2,
    'stream_retry_delay': 0.5,
    'system_prompt': '',
    'temperature': 0.7,
    'tool_calling': True,
    'tool_max_result_chars': 100000,
    'tool_output_log': True,
    'tool_permission': {
        'ask': 'allow',
        'bash': 'ask',
        'call': 'allow',
        'catalog': 'allow',
        'delegate': 'allow',
        'edit': 'allow',
        'list': 'allow',
        'mcp': 'ask',
        'read': 'allow',
        'vcs': 'ask',
        'web': 'allow',
    },
    'tools.allow': [],
    'tools.deny': [],
}

VERBOSITY_SCOPES = ('thinking', 'output', 'status', 'tools', 'footer')
VERBOSITY_VALUES = {
    'thinking': ('off', 'summary', 'assistant', 'agent', 'all'),
    'output': ('off', 'assistant', 'agent', 'all'),
    'status': ('off', 'on'),
    'tools': ('off', 'summary', 'full'),
    'footer': ('off', 'summary', 'full'),
}
VERBOSITY_LEVELS = ('off', 'assistant', 'agent', 'all', 'summary', 'full', 'on')
VERBOSITY_PRESETS = {
    'quiet': {'thinking': 'off', 'output': 'off', 'status': 'off',
              'tools': 'off', 'footer': 'summary'},
    'normal': {'thinking': 'summary', 'output': 'agent', 'status': 'on',
               'tools': 'summary', 'footer': 'summary'},
    'verbose': {'thinking': 'all', 'output': 'all', 'status': 'on',
                'tools': 'full', 'footer': 'full'},
}

def verbosity_level(config, scope: str) -> str:
    name = str(scope or '').strip().lower()
    if name not in VERBOSITY_SCOPES:
        return 'summary'
    values = VERBOSITY_VALUES.get(name, ())
    if config is None:
        return values[0] if values else 'summary'
    value = str(config.get(f'verbosity.{name}', 'inherit') or 'inherit')
    value = value.strip().lower()
    if value in values:
        return value
    if name == 'thinking' and value == 'full':
        return 'all'
    if name == 'output' and value in ('summary', 'full'):
        return 'assistant' if value == 'summary' else 'all'
    preset = str(config.get('verbosity', 'normal') or 'normal').strip().lower()
    return VERBOSITY_PRESETS.get(preset, VERBOSITY_PRESETS['normal'])[name]

def config_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on', 'y'):
        return True
    if text in ('0', 'false', 'no', 'off', 'n', ''):
        return False
    return default


CONFIG_DESCRIPTIONS = {
    'access': 'Read-class permission keys; any key not listed is write-class',
    'ask_min_question_chars': 'Minimum direction-ask question length without context or options',
    'ask_policy': 'Routing for the ask tool by kind',
    'auto_continue_max': 'Max continuation rounds per turn (0 is off)',
    'base_url': 'Provider endpoint',
    'clear_screen': 'Clear the screen before the REPL banner',
    'compact_at': 'Compaction limit: a fraction of context_window when below 1, absolute tokens when above 1',
    'compact_auto': 'Enable automatic compaction when the context approaches the limit',
    'compact_before': 'Rounds of headroom used to project the next context size',
    'compact_keep': 'Rounds to keep when compacting the provider context',
    'context_window': 'Model context window in tokens, 0 = unknown',
    'cost.rates': 'USD per 1M tokens keyed by provider/model, provider, then default',
    'delegate_depth': 'Maximum nested delegate siblings',
    'grant_permission': 'Ceiling on what a run may hand down to sub-agents',
    'max_team_depth': 'Maximum nested team runs',
    'max_tokens': 'Output token cap sent to the provider',
    'mode': 'Active agent mode (read or write)',
    'model': 'Model name or provider/model ref',
    'modes': 'Mode instruction blocks and prompt colors',
    'plugins': 'Plugins to load (empty loads all)',
    'project_instructions': 'Per-worktree instructions file loaded into the system prompt',
    'reasoning': 'Request reasoning and control its token budget',
    'session.storage': 'Session storage format: json, jsonl, or sqlite',
    'show_version': 'Show the version in the REPL banner',
    'stream_retries': 'Extra attempts when a stream ends without content',
    'stream_retry_delay': 'Seconds between stream retries',
    'system_prompt': 'The root instruction, composed with the active mode',
    'temperature': 'Sampling temperature',
    'tool_calling': 'Enable OpenAI-compatible function calling',
    'tool_max_result_chars': 'Cap tool-result content returned to the model',
    'tool_output_log': 'Append tool results to one log beside the session',
    'tool_permission': 'Category permission actions',
    'tools.allow': 'Name-level allowlist',
    'tools.deny': 'Name-level deny list',
}

CONFIG_VALUE_INLINE = 40

CONFIG_CHOICES = {
    'verbosity': ('quiet', 'normal', 'verbose'),
    'verbosity.thinking': ('off', 'assistant', 'agent', 'all', 'inherit'),
    'verbosity.output': ('off', 'assistant', 'agent', 'all', 'inherit'),
    'verbosity.status': ('off', 'on', 'inherit'),
    'verbosity.tools': ('off', 'summary', 'full', 'inherit'),
    'verbosity.footer': ('off', 'summary', 'full', 'inherit'),
    'word_streaming': ('true', 'false'),
}


_MISSING = object()


def _merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class Config:
    GLOBAL_DIR: Path | None = None

    def __init__(self, path: str | None = None):
        global_home = self.GLOBAL_DIR if self.GLOBAL_DIR is not None else Path.home()
        self.global_path = global_home / '.config' / 'polyglav' / 'config.json'
        if path:
            self.local_path = Path(path).resolve() / '.polyglav' / 'config.json'
        else:
            self.local_path = Path.cwd() / '.polyglav' / 'config.json'
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self._global_raw: dict = {}
        self._local_raw: dict = {}
        self._plugin_defaults: dict = {}
        self.plugin_descriptions: dict = {}
        self.plugin_owners: dict = {}
        self._applied: dict = {}
        self._load()

    def _load(self):
        if self.global_path.exists():
            with open(self.global_path) as f:
                self._global_raw = json.load(f)
        if self.local_path.exists():
            with open(self.local_path) as f:
                self._local_raw = json.load(f)
        self.data = self._merged()

    def _merged(self) -> dict:
        base = _merge(DEFAULT_CONFIG, self._plugin_defaults)
        merged = _merge(_merge(base, self._global_raw), self._local_raw)
        merged.update(self._applied)
        return merged

    def register_plugin_defaults(self, defaults: dict,
                                 owner: str = '') -> None:
        changed = False
        for key, entry in (defaults or {}).items():
            if not isinstance(entry, dict):
                continue
            if key not in self._plugin_defaults:
                self._plugin_defaults[key] = copy.deepcopy(
                    entry.get('default'))
                changed = True
            description = entry.get('description')
            if description and key not in self.plugin_descriptions:
                self.plugin_descriptions[key] = str(description)
                changed = True
            if owner and key not in self.plugin_owners:
                self.plugin_owners[key] = str(owner)
        if changed:
            self.data = self._merged()

    def reload(self):
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self._global_raw = {}
        self._local_raw = {}
        self._applied = {}
        self._load()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def apply(self, key, value):
        self._applied[key] = value
        self.data[key] = value

    def set(self, key, value, scope: str = 'local'):
        self._applied.pop(key, None)
        raw = self._global_raw if scope == 'global' else self._local_raw
        raw[key] = value
        if scope == 'global':
            local_value = self._local_raw.get(key)
            if local_value == '':
                local_value = None
            if key not in self._local_raw or local_value is None:
                self.data[key] = value
            self._write_global({})
        else:
            self.data[key] = value
            self._save_local()

    def unset(self, key, scope: str = 'local'):
        self._applied.pop(key, None)
        raw = self._global_raw if scope == 'global' else self._local_raw
        raw.pop(key, None)
        value = self._merged().get(key, _MISSING)
        if value is _MISSING:
            self.data.pop(key, None)
        else:
            self.data[key] = value
        if scope == 'global':
            self._write_global({})
        else:
            self._save_local()

    def origin(self, key: str) -> str:
        if key in self._local_raw:
            return 'local'
        if key in self._global_raw:
            return 'global'
        return 'default'

    def save(self):
        self._save_local()

    def _save_local(self):
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(self._local_raw, indent=2))

    def _write_global(self, patch: dict):
        self._global_raw.update(patch)
        self.global_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_path.write_text(json.dumps(self._global_raw, indent=2))
