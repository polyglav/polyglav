import unittest

from polyglav.tools.registry import ToolRegistry


class TestToolRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = ToolRegistry()

        @self.registry.register(
            name='search_web', description='Search the web',
            parameters={
                'type': 'object',
                'properties': {'query': {'type': 'string'}},
                'required': ['query'],
            },
            refine=True, category='search', permission='web', key_arg='query',
            short='Search the web', param_aliases={'q': 'query'},
            note=lambda r: r == 'No results found.',
        )
        def search_web(query):
            return f'results for {query}'

        @self.registry.register(
            name='run_cmd', description='Run a shell command',
            parameters={
                'type': 'object',
                'properties': {
                    'command': {'type': 'string'},
                    'cwd': {'type': 'string'},
                    'timeout': {'type': 'integer'},
                },
                'required': ['command'],
            },
            category='exec', permission='bash', key_arg='command',
            short='Run a shell command', echo=True,
            aliases=['exec'], param_aliases={'cmd': 'command'},
            glyph='$', verb='Run',
        )
        def run_cmd(command, cwd=None, timeout=30):
            return f'ran {command}'

        @self.registry.register(
            name='read_doc', description='Read a file',
            parameters={
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'limit': {'type': 'integer'},
                },
                'required': ['path'],
            },
            category='read', permission='read', path_arg='path', key_arg='path',
            glyph='←', verb='Read', param_aliases={'file': 'path'},
            note=lambda r: r.endswith('(empty)'),
        )
        def read_doc(path, limit=0):
            return path

        @self.registry.register(
            name='list_dir', description='List a directory',
            parameters={
                'type': 'object',
                'properties': {'path': {'type': 'string'}},
                'required': ['path'],
            },
            category='read', permission='list', path_arg='path', key_arg='path',
            glyph='*', verb='List',
        )
        def list_dir(path):
            return path

        @self.registry.register(
            name='glob_files', description='Glob',
            parameters={
                'type': 'object',
                'properties': {'pattern': {'type': 'string'}},
                'required': ['pattern'],
            },
            category='read', permission='list', key_arg='pattern',
            glyph='*', verb='Glob',
        )
        def glob_files(pattern):
            return pattern

        @self.registry.register(
            name='write_doc', description='Write a file',
            parameters={
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'content': {'type': 'string'},
                },
                'required': ['path', 'content'],
            },
            category='write', permission='edit', path_arg='path', key_arg='path',
            glyph='→', verb='Write',
            status=lambda args: f"{args.get('path')}\n"
                                + '\n'.join(f'+ {l}'
                                            for l in args.get('content', '').splitlines()),
        )
        def write_doc(path, content):
            return content

    def test_refine_metadata(self):
        self.assertTrue(self.registry.refine_required('search_web'))
        self.assertFalse(self.registry.refine_required('read_doc'))
        self.assertFalse(self.registry.refine_required('nonexistent'))

    def test_names(self):
        self.assertIn('search_web', self.registry.names())
        self.assertIn('read_doc', self.registry.names())

    def test_schema_order_includes_aliases(self):
        names = [s['function']['name'] for s in self.registry.schema()]
        self.assertEqual(names, [
            'search_web', 'run_cmd', 'exec',
            'read_doc', 'list_dir', 'glob_files', 'write_doc',
        ])

    def test_execute_drops_undeclared_and_none_args(self):
        out = self.registry.execute('list_dir',
                                    {'path': '.', 'depth': None, 'bogus': 1})
        self.assertNotIn('Error', out)

    def test_execute_unknown_tool(self):
        out = self.registry.execute('nonexistent', {})
        self.assertIn('unknown tool', out)

    def test_execute_passes_config_to_declared_handler(self):
        reg = ToolRegistry()
        params = {'type': 'object', 'properties': {}, 'required': []}
        seen = {}

        @reg.register('peek_cfg', 'Peek', params)
        def peek_cfg(_config=None):
            seen['config'] = _config
            return 'ok'

        class FakeConfig:
            def get(self, key, default=None):
                return default

        out = reg.execute('peek_cfg', {}, config=FakeConfig())
        self.assertEqual(out, 'ok')
        self.assertIsNotNone(seen['config'])

    def test_execute_ignores_config_for_plain_handler(self):
        reg = ToolRegistry()
        params = {'type': 'object', 'properties': {}, 'required': []}

        @reg.register('plain', 'Plain', params)
        def plain():
            return 'ok'

        out = reg.execute('plain', {}, config=object())
        self.assertEqual(out, 'ok')

    def test_custom_refine_metadata(self):
        reg = ToolRegistry()

        @reg.register('do_stuff', 'Do something', {}, refine=True)
        def do_stuff():
            return 'ok'

        self.assertTrue(reg.refine_required('do_stuff'))

    def test_permission_metadata(self):
        self.assertEqual(self.registry.permission_for('search_web'), 'web')
        self.assertEqual(self.registry.permission_for('read_doc'), 'read')
        self.assertEqual(self.registry.key_arg_for('search_web'), 'query')
        self.assertEqual(self.registry.path_arg_for('read_doc'), 'path')
        self.assertEqual(self.registry.path_arg_for('search_web'), None)

    def test_schema_filtered(self):
        schema = self.registry.schema_filtered({'search_web'})
        names = [s['function']['name'] for s in schema]
        self.assertEqual(names, ['search_web'])

    def test_schema_filtered_advertises_canonical_only(self):
        allowed = {'search_web', 'run_cmd', 'read_doc', 'list_dir',
                   'glob_files', 'write_doc', 'exec'}
        names = [s['function']['name'] for s in self.registry.schema_filtered(allowed)]
        self.assertEqual(names, [
            'search_web', 'run_cmd', 'read_doc', 'list_dir', 'glob_files', 'write_doc',
        ])

    def test_schema_filtered_hides_denied_canonical_even_if_alias_allowed(self):
        names = [s['function']['name'] for s in self.registry.schema_filtered({'exec'})]
        self.assertEqual(names, [])

    def test_status_parts_uses_key_arg_value(self):
        value, body = self.registry.status_parts(
            'search_web', {'query': 'latest python', 'junk': 1})
        self.assertEqual(value, 'latest python')
        self.assertEqual(body, [])

    def test_status_parts_truncates_long_value(self):
        value, body = self.registry.status_parts('run_cmd', {'command': 'x' * 200})
        self.assertEqual(len(value), 80)
        self.assertEqual(body, [])

    def test_status_parts_custom_status_source_note_or_status(self):
        value, body = self.registry.status_parts(
            'write_doc', {'path': 'a.md', 'content': 'First line\nSecond line\n'})
        self.assertEqual(value, 'a.md')
        self.assertEqual(body[:2], ['+ First line', '+ Second line'])

    def test_status_parts_unknown_tool(self):
        value, body = self.registry.status_parts('nonexistent', {})
        self.assertEqual(value, 'nonexistent')
        self.assertEqual(body, [])

    def test_echo_metadata(self):
        self.assertTrue(self.registry.echo_for('run_cmd'))
        self.assertFalse(self.registry.echo_for('write_doc'))
        self.assertFalse(self.registry.echo_for('nonexistent'))

    def test_note_metadata(self):
        self.assertTrue(self.registry.is_note_result('search_web', 'No results found.'))
        self.assertTrue(self.registry.is_note_result('read_doc', '# x\n(empty)'))
        self.assertFalse(self.registry.is_note_result('read_doc', '(empty dir)'))
        self.assertFalse(self.registry.is_note_result('search_web', 'Some results found.'))
        self.assertFalse(self.registry.is_note_result('nonexistent', '(empty)'))

    def test_activity_category_defaults(self):
        self.assertEqual(self.registry.activity('search_web', {'query': 'hi there'}),
                         ('%', 'Search', 'hi there', ''))
        self.assertEqual(self.registry.activity('run_cmd', {'command': 'echo hi'}),
                         ('$', 'Run', 'echo hi', ''))
        self.assertEqual(self.registry.activity('write_doc', {'path': 'a.md', 'content': 'x'}),
                         ('→', 'Write', 'a.md', 'content=x'))
        self.assertEqual(self.registry.activity('read_doc', {'path': 'a.py'}),
                         ('←', 'Read', 'a.py', ''))

    def test_activity_params_exclude_key_arg_in_schema_order(self):
        self.assertEqual(
            self.registry.activity('run_cmd',
                                   {'command': 'ls', 'cwd': '/workspace', 'timeout': 10000}),
            ('$', 'Run', 'ls', 'cwd=/workspace, timeout=10000'))

    def test_activity_params_aliases_resolved(self):
        self.assertEqual(
            self.registry.activity('read_doc', {'file': 'a.py', 'limit': 5}),
            ('←', 'Read', 'a.py', 'limit=5'))

    def test_params_str_compacts_large_and_multiline_values(self):
        params = self.registry.params_str(
            'write_doc', {'path': 'a.md', 'content': 'x' * 100})
        self.assertIn('content=<100 chars>', params)
        params = self.registry.params_str(
            'write_doc', {'path': 'a.md', 'content': 'a\nb'})
        self.assertIn('content=<3 chars>', params)

    def test_activity_per_tool_override(self):
        self.assertEqual(self.registry.activity('glob_files', {'pattern': '**/*.py'}),
                         ('*', 'Glob', '**/*.py', ''))
        self.assertEqual(self.registry.activity('list_dir', {'path': 'x'}),
                         ('*', 'List', 'x', ''))

    def test_activity_truncates_long_value(self):
        glyph, verb, label, params = self.registry.activity('run_cmd', {'command': 'x' * 200})
        self.assertEqual((glyph, verb), ('$', 'Run'))
        self.assertEqual(len(label), 80)
        self.assertEqual(params, '')

    def test_activity_missing_key_arg_falls_back_to_name(self):
        self.assertEqual(self.registry.activity('run_cmd', {}),
                         ('$', 'Run', 'run_cmd', ''))

    def test_activity_unknown_tool(self):
        self.assertIsNone(self.registry.activity('nonexistent', {}))

    def test_activity_unmapped_category(self):
        reg = ToolRegistry()
        params = {'type': 'object', 'properties': {}, 'required': []}

        @reg.register('do_stuff', 'Do something', params, category='custom')
        def do_stuff():
            return 'ok'

        self.assertIsNone(reg.activity('do_stuff', {}))

    def test_activity_partial_override_keeps_category_default(self):
        reg = ToolRegistry()
        params = {'type': 'object',
                  'properties': {'path': {'type': 'string'}},
                  'required': ['path']}

        @reg.register('peek_dir', 'Peek', params, category='read', key_arg='path',
                      verb='Scan')
        def peek_dir(path):
            return 'ok'

        self.assertEqual(reg.activity('peek_dir', {'path': '/x'}),
                         ('←', 'Scan', '/x', ''))

    def test_custom_status_callback(self):
        reg = ToolRegistry()
        params = {
            'type': 'object',
            'properties': {'path': {'type': 'string'},
                           'content': {'type': 'string'}},
            'required': ['path', 'content'],
        }

        @reg.register('do_stuff', 'Do', params, key_arg='path',
                      status=lambda args: f"{args['path']}\n+ {args['content']}")
        def do_stuff(path, content):
            return 'ok'

        value, body = reg.status_parts('do_stuff', {'path': 'p', 'content': 'c'})
        self.assertEqual(value, 'p')
        self.assertEqual(body, ['+ c'])

    def test_write_actions_metadata(self):
        reg = ToolRegistry()

        @reg.register('catalog_like', 'C',
                      {'type': 'object', 'properties': {}},
                      category='catalog', permission='catalog',
                      write_actions=['save', 'remove'])
        def catalog_like():
            return 'ok'

        @reg.register('reader', 'R', {'type': 'object', 'properties': {}},
                      permission='read')
        def reader():
            return 'ok'

        self.assertEqual(reg.write_action_keys(), {'catalog'})


if __name__ == '__main__':
    unittest.main()