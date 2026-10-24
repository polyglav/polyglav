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
    'auto_continue': True,
    'auto_continue_max': 2,
    'base_url': 'https://api.ollama.com',
    'clear_screen': True,
    'compact_keep': 4,
    'confirm_timeout': 0,
    'connect_check': True,
    'delegate_depth': 1,
    'footer_tokens': ['context'],
    'glyphs': {},
    'grant_permission': {},
    'hide_confirm_input': True,
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
            'cap': 'read',
            'description': 'Plan: assistant, chat, and planning tasks',
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
            'color': 'cyan',
        },
        'write': {
            'cap': 'write',
            'description': ('Work: working tasks, tools, edits, commands, '
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
    'output_log': False,
    'output_log_ansi': False,
    'output_log_dir': '.polyglav/output',
    'plan': {
        'dir': '.polyglav/plans',
    },
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
    'provider': 'ollama',
    'query_refine': False,
    'query_refine_context': 4,
    'query_refine_min_words': 3,
    'reasoning': 'auto',
    'report.webhook': '',
    'search_results': 5,
    'show_version': True,
    'stream_retries': 2,
    'stream_retry_delay': 0.5,
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
        'list': 'allow',
        'mcp': 'ask',
        'read': 'allow',
        'vcs': 'ask',
        'web': 'allow',
    },
    'tools.allow': [],
    'tools.deny': [],
    'tools_output_drop': ['web_fetch', 'open', 'fetch_page'],
    'tools_output_dir': '.polyglav/tmp/',
    'tools_output_max_chars': 0,
    'tools_output_spill': False,
    'tools_output_tmp_max_bytes': 50000000,
    'unattended': False,
    'verbosity': 'normal',
    'verbosity.footer': 'inherit',
    'verbosity.subruns': 'inherit',
    'verbosity.thinking': 'inherit',
    'verbosity.tools': 'inherit',
    'web_search': False,
    'word_streaming': True,
}

VERBOSITY_SCOPES = ('thinking', 'tools', 'subruns', 'footer')
VERBOSITY_LEVELS = ('off', 'summary', 'full')
VERBOSITY_PRESETS = {
    'quiet': {'thinking': 'off', 'tools': 'off',
              'subruns': 'summary', 'footer': 'summary'},
    'normal': {'thinking': 'summary', 'tools': 'summary',
               'subruns': 'summary', 'footer': 'summary'},
    'verbose': {'thinking': 'full', 'tools': 'full',
                'subruns': 'full', 'footer': 'full'},
}
VERBOSITY_OLD_KEYS = (
    'delegate_echo', 'glyph_lines', 'glyph_params', 'show_context_size',
    'show_errors', 'show_notes', 'show_tool_output', 'show_thinking',
    'show_thought_duration', 'status_spinner', 'subrun_verbosity',
    'tool_status_visible',
)


def verbosity_level(config, scope: str) -> str:
    name = str(scope or '').strip().lower()
    if config is None or name not in VERBOSITY_SCOPES:
        return 'summary'
    value = str(config.get(f'verbosity.{name}', 'inherit') or 'inherit')
    value = value.strip().lower()
    if value in VERBOSITY_LEVELS:
        return value
    preset = str(config.get('verbosity', 'normal') or 'normal').strip().lower()
    return VERBOSITY_PRESETS.get(preset, VERBOSITY_PRESETS['normal'])[name]

CONFIG_DESCRIPTIONS = {
    'access': 'Read-class permission keys; any key not listed is write-class',
    'api_key': 'Legacy, ignored (API keys live in providers.json)',
    'ask_min_question_chars': 'Minimum direction-ask question length without context or options',
    'ask_policy': 'Routing for the ask tool by kind',
    'auto_continue': 'Re-request on truncation and stitch the parts',
    'auto_continue_max': 'Max continuation rounds per turn',
    'base_url': 'Provider endpoint',
    'clear_screen': 'Clear the screen before the REPL banner',
    'compact_keep': 'Turns to keep when compacting the provider context',
    'confirm_timeout': 'Seconds a confirm or ask prompt waits before auto-denying',
    'connect_check': 'Probe the provider connection on config changes',
    'delegate_depth': 'Maximum nested delegate siblings',
    'footer_tokens': 'Token counts the footer shows, in order',
    'glyphs': 'Glyph overrides, or "ascii" for the ASCII preset',
    'grant_permission': 'Ceiling on what a run may hand down to sub-agents',
    'hide_confirm_input': 'Hide typed input for the tool confirm prompt',
    'list_dir_max_entries': 'Cap entries list_dir returns',
    'markdown_streaming': 'Basic markdown-aware streaming',
    'max_team_depth': 'Maximum nested team runs',
    'max_tokens': 'Output token cap sent to the provider',
    'mcp.servers': 'MCP client server definitions',
    'mcp_server.allow_ask': 'When serving MCP, run ask-policy tools vs refuse them',
    'memory': 'Enable bounded memory summaries under .polyglav/memory/',
    'memory_max_chars': 'Cap characters of an injected memory summary',
    'memory_scopes': 'Per-scope memory toggles',
    'mode': 'Active agent mode (read or write)',
    'model': 'Model name or provider/model ref',
    'modes': 'Mode instruction blocks and prompt colors',
    'output_log': 'Write everything the REPL prints to a file',
    'output_log_ansi': 'Keep ANSI colors in the output log',
    'output_log_dir': 'Directory for the output log',
    'plugins': 'Plugins to load (empty loads all)',
    'print_max_chars': 'Cap characters /print shows per part',
    'project_instructions': 'Per-worktree instructions file loaded into the system prompt',
    'provider': 'Provider name',
    'query_refine': 'Auto-refine short web-search queries',
    'query_refine_context': 'Recent-message context for refinement',
    'query_refine_min_words': 'Minimum query length before refinement applies',
    'reasoning': 'Request reasoning and control its token budget',
    'report.webhook': 'URL a completed job run is POSTed to',
    'search_results': 'Number of search results to fetch',
    'session_tool_max_chars': 'Legacy, renamed tools_output_max_chars',
    'show_version': 'Show the version in the REPL banner',
    'stream_retries': 'Extra attempts when a stream ends without content',
    'stream_retry_delay': 'Seconds between stream retries',
    'system_prompt': 'The root instruction, composed with the active mode',
    'temperature': 'Sampling temperature',
    'tool_analysis': 'Model-generated one-line analysis of each tool result',
    'tool_calling': 'Enable OpenAI-compatible function calling',
    'tool_max_result_chars': 'Cap tool-result content returned to the model',
    'tool_permission': 'Category permission actions',
    'tools.allow': 'Name-level allowlist',
    'tools.deny': 'Name-level deny list',
    'tools_output_drop': 'Tool results replaced by a marker in persisted sessions',
    'tools_output_dir': 'Persistent tool output folder when tools_output_spill is on',
    'tools_output_max_chars': 'Cap persisted tool-result content',
    'tools_output_spill': 'Persist tool output to tools_output_dir instead of the system temp directory',
    'tools_output_tmp_max_bytes': 'Cap on total spilled tool output size',
    'unattended': 'No stdin at any depth; confirms auto-deny, user asks park',
    'verbosity': 'Display volume: quiet, normal, or verbose',
    'verbosity.footer': 'Footer detail: off, summary, full, or inherit',
    'verbosity.subruns': 'Sub-run detail: off, summary, full, or inherit',
    'verbosity.thinking': 'Thinking detail: off, summary, full, or inherit',
    'verbosity.tools': 'Tool detail: off, summary, full, or inherit',
    'web_search': 'Search the web before answering',
    'word_streaming': 'Buffer output to word boundaries',
}

CONFIG_VALUE_INLINE = 40

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
        self._migrate_output_keys()
        self._migrate_verbosity()

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

    def _migrate_verbosity(self):
        local = self._migrate_verbosity_raw(self._local_raw)
        global_ = self._migrate_verbosity_raw(self._global_raw)
        if local or global_:
            self.data = self._merged()
        if local:
            self._save_local()
        if global_:
            self._write_global({})

    @staticmethod
    def _migrate_verbosity_raw(raw: dict) -> bool:
        old = [key for key in VERBOSITY_OLD_KEYS if key in raw]
        if not old:
            return False
        if ('verbosity.thinking' not in raw
                and any(key in raw for key in
                        ('show_thinking', 'show_thought_duration'))):
            if raw.get('show_thinking') is True:
                raw['verbosity.thinking'] = 'full'
            elif raw.get('show_thought_duration') is False:
                raw['verbosity.thinking'] = 'off'
            else:
                raw['verbosity.thinking'] = 'summary'
        if ('verbosity.tools' not in raw
                and any(key in raw for key in
                        ('show_tool_output', 'show_notes',
                         'glyph_lines', 'glyph_params'))):
            if raw.get('show_tool_output') is True:
                raw['verbosity.tools'] = 'full'
            elif raw.get('glyph_lines') is False or raw.get('show_notes') is False:
                raw['verbosity.tools'] = 'off'
            else:
                raw['verbosity.tools'] = 'summary'
        if ('verbosity.tools' not in raw and 'tool_status_visible' in raw):
            raw['verbosity.tools'] = (
                'summary' if raw.get('tool_status_visible') else 'off')
        if ('verbosity.subruns' not in raw
                and any(key in raw for key in
                        ('subrun_verbosity', 'delegate_echo', 'status_spinner'))):
            if str(raw.get('subrun_verbosity', '')).lower() == 'full':
                raw['verbosity.subruns'] = 'full'
            elif (raw.get('delegate_echo') is False
                  or raw.get('status_spinner') is False):
                raw['verbosity.subruns'] = 'off'
            else:
                raw['verbosity.subruns'] = 'summary'
        if 'verbosity.footer' not in raw and 'show_context_size' in raw:
            raw['verbosity.footer'] = (
                'full' if raw.get('show_context_size') is not False else 'summary')
        for key in old:
            raw.pop(key, None)
        return True

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
