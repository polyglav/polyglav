import copy
import json
from pathlib import Path


DEFAULT_CONFIG = {
    'access': {
        'read_tools': ['read', 'list', 'web', 'catalog', 'ask', 'handoff',
                       'offload'],
    },
    'ask_min_question_chars': 8,
    'ask_options_inline_chars': 60,
    'ask_policy': {
        'permission': 'auto',
        'direction': '',
    },
    'auto_continue': True,
    'auto_continue_max': 2,
    'base_url': 'https://api.ollama.com',
    'clear_screen': True,
    'compact_keep': 4,
    'confirm_timeout': 0,
    'connect_check': True,
    'delegate_echo': True,
    'focus_on_delegate': 'on',
    'footer_tokens': ['context'],
    'glyph_lines': True,
    'glyph_params': True,
    'grant_permission': {},
    'hide_confirm_input': False,
    'list_dir_max_entries': 200,
    'markdown_streaming': False,
    'max_team_depth': 2,
    'max_tokens': 8192,
    'mcp.servers': [],
    'mcp_server.allow_ask': True,
    'memory': True,
    'memory_max_chars': 2000,
    'memory_scopes': {'role': True, 'team': True, 'job': True},
    'mode': 'read',
    'model': 'llama3.2',
    'modes': {
        'read': {
            'system_prompt': (
                'You are in read mode (read-only). Investigate, cite sources, and '
                'propose a plan; do not modify files or run commands. Write and '
                'exec tools are disabled.'
            ),
            'color': 'cyan',
        },
        'write': {'system_prompt': '', 'color': 'orange'},
    },
    'offload_depth': 1,
    'output_log': False,
    'output_log_ansi': False,
    'output_log_dir': '.polyglav/output',
    'plugins': [
        'polyglav-core-anthropic',
        'polyglav-core-dev',
        'polyglav-core-edit',
        'polyglav-core-eval',
        'polyglav-core-exec',
        'polyglav-core-fs',
        'polyglav-core-git',
        'polyglav-core-groq',
        'polyglav-core-mcp',
        'polyglav-core-ollama',
        'polyglav-core-onboarding',
        'polyglav-core-openai',
        'polyglav-core-opencode',
        'polyglav-core-web',
        'polyglav-core-webhook',
    ],
    'print_max_chars': 4000,
    'project_instructions': 'AGENTS.md',
    'prompt_role': True,
    'provider': 'ollama',
    'query_refine': False,
    'query_refine_context': 4,
    'query_refine_min_words': 3,
    'reasoning': 'auto',
    'report.webhook': '',
    'run_buffer_max_lines': 2000,
    'search_results': 5,
    'show_context_size': True,
    'show_errors': True,
    'show_notes': True,
    'show_thinking': False,
    'show_thought_duration': True,
    'show_version': True,
    'status_spinner': True,
    'stream_retries': 2,
    'stream_retry_delay': 0.5,
    'subrun_verbosity': 'quiet',
    'system_prompt': '',
    'temperature': 0.7,
    'tool_analysis': False,
    'tool_calling': True,
    'tool_max_result_chars': 100000,
    'tool_permission': {
        'ask': 'allow',
        'bash': 'ask',
        'bash_allow': [],
        'call': 'allow',
        'catalog': 'allow',
        'delegate': 'allow',
        'edit': 'allow',
        'handoff': 'allow',
        'list': 'allow',
        'mcp': 'ask',
        'offload': 'allow',
        'read': 'allow',
        'vcs': 'ask',
        'web': 'allow',
    },
    'tool_status_visible': True,
    'tools.allow': [],
    'tools.deny': [],
    'tools_output_drop': ['web_fetch', 'open', 'fetch_page'],
    'tools_output_max_chars': 0,
    'unattended': False,
    'web_search': False,
    'word_streaming': True,
}

_NEW_PROVIDER_PLUGINS = ['polyglav-core-opencode', 'polyglav-core-ollama',
                         'polyglav-core-openai', 'polyglav-core-groq',
                         'polyglav-core-anthropic']

_OUTPUT_KEY_ALIASES = {
    'noise_tools': 'tools_output_drop',
    'session_tool_max_chars': 'tools_output_max_chars',
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
        self._load()

    def _load(self):
        if self.global_path.exists():
            with open(self.global_path) as f:
                self._global_raw = json.load(f)
        if self.local_path.exists():
            with open(self.local_path) as f:
                self._local_raw = json.load(f)
        self.data = self._merged()
        self._migrate_plugins()
        self._migrate_output_keys()

    def _merged(self) -> dict:
        return _merge(_merge(DEFAULT_CONFIG, self._global_raw), self._local_raw)

    def _migrate_output_keys(self):
        local = self._rename_output_keys(self._local_raw)
        global_ = self._rename_output_keys(self._global_raw)
        if local or global_:
            self.data = self._merged()
        if local:
            self._save_local()
        if global_:
            self._write_global({})

    @staticmethod
    def _rename_output_keys(raw: dict) -> bool:
        changed = False
        for old, new in _OUTPUT_KEY_ALIASES.items():
            if old not in raw:
                continue
            if new not in raw:
                raw[new] = raw[old]
            raw.pop(old, None)
            changed = True
        return changed

    def _migrate_plugins(self):
        plugins = self.data.get('plugins')
        if not isinstance(plugins, list) or not plugins:
            return
        missing = [n for n in DEFAULT_CONFIG['plugins']
                   if n in _NEW_PROVIDER_PLUGINS and n not in plugins]
        if not missing:
            return
        plugins = plugins + missing
        self.data['plugins'] = plugins
        if 'plugins' in self._global_raw:
            self._global_raw['plugins'] = plugins
            self._write_global({})
        else:
            self._local_raw['plugins'] = plugins
            self._save_local()

    def reload(self):
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self._global_raw = {}
        self._local_raw = {}
        self._load()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def apply(self, key, value):
        self.data[key] = value

    def set(self, key, value, scope: str = 'local'):
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
