import copy
import json
from pathlib import Path


DEFAULT_CONFIG = {
    'provider': 'ollama',
    'model': 'llama3.2',
    'base_url': 'https://api.ollama.com',
    'temperature': 0.7,
    'max_tokens': 8192,
    'max_team_depth': 2,
    'unattended': False,
    'confirm_timeout': 0,
    'hide_confirm_input': False,
    'system_prompt': '',
    'assistant': True,
    'assistant_role': 'assistant',
    'prompt_role': False,
    'focus_on_delegate': 'on',
    'memory': True,
    'memory_scopes': {'role': True, 'team': True, 'job': True},
    'memory_max_chars': 2000,
    'mode': 'read',
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
    'access': {
        'read_tools': ['read', 'list', 'web', 'catalog', 'ask', 'handoff',
                       'offload'],
    },
    'tool_calling': True,
    'tool_status_visible': True,
    'delegate_echo': True,
    'glyph_lines': True,
    'glyph_params': True,
    'show_errors': True,
    'show_notes': True,
    'tool_analysis': False,
    'session_tool_max_chars': 0,
    'print_max_chars': 4000,
    'tool_max_result_chars': 100000,
    'list_dir_max_entries': 200,
    'connect_check': True,
    'stream_retries': 2,
    'stream_retry_delay': 0.5,
    'auto_continue': True,
    'auto_continue_max': 2,
    'query_refine': False,
    'query_refine_min_words': 3,
    'query_refine_context': 4,
    'report.webhook': '',
    'show_thinking': False,
    'show_thought_duration': True,
    'status_spinner': True,
    'subrun_verbosity': 'quiet',
    'run_buffer_max_lines': 2000,
    'output_log': False,
    'output_log_dir': '.polyglav/output',
    'reasoning': 'auto',
    'markdown_streaming': False,
    'word_streaming': True,
    'show_context_size': True,
    'footer_tokens': ['context'],
    'clear_screen': True,
    'show_version': True,
    'compact_keep': 4,
    'project_instructions': 'AGENTS.md',
    'noise_tools': ['web_fetch', 'open', 'fetch_page'],
    'web_search': False,
    'search_results': 5,
    'tools.allow': [],
    'tools.deny': [],
    'grant_permission': {},
    'ask_policy': {
        'permission': 'auto',
        'direction': 'human',
    },
    'tool_permission': {
        'ask': 'allow',
        'bash': 'ask',
        'bash_allow': [],
        'catalog': 'allow',
        'delegate': 'allow',
        'edit': 'allow',
        'handoff': 'allow',
        'list': 'allow',
        'mcp': 'ask',
        'read': 'allow',
        'team': 'allow',
        'vcs': 'ask',
        'web': 'allow',
    },
    'mcp.servers': [],
    'mcp_server.allow_ask': True,
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
        'polyglav-core-openai',
        'polyglav-core-opencode',
        'polyglav-core-web',
        'polyglav-core-webhook',
    ],
    'report.webhook': '',
}

_NEW_PROVIDER_PLUGINS = ['polyglav-core-opencode', 'polyglav-core-ollama',
                         'polyglav-core-openai', 'polyglav-core-groq',
                         'polyglav-core-anthropic']

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

    def _merged(self) -> dict:
        return _merge(_merge(DEFAULT_CONFIG, self._global_raw), self._local_raw)

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
