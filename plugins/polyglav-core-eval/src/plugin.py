def _large_file() -> str:
    return '\n'.join(f'line {i} of the big source file, padded to a useful width'
                     for i in range(1, 4001)) + '\n'


def register_fixtures(fixtures):
    fixtures.update({
        'read-file-lines': {
            'description': 'Read a file and report its line count',
            'task': 'Read src/app.py and report how many lines it has.',
            'files': {
                'src/app.py': (
                    'import sys\n'
                    '\n'
                    'def main():\n'
                    '    return 0\n'
                    '\n'
                    'if __name__ == "__main__":\n'
                    '    sys.exit(main())\n'
                ),
            },
            'expected': ['file_read'],
            'verifier': {
                'must_include': ['file_read'],
                'avoid': ['run_command'],
                'max_calls': 2,
            },
        },
        'find-then-read': {
            'description': 'Locate a file by glob, then read it',
            'task': 'Find the Python file under src that defines greet and read it.',
            'files': {
                'src/one.py': 'def greet():\n    return "hi"\n',
                'src/two.py': 'value = 1\n',
            },
            'expected': ['glob', 'file_read'],
            'verifier': {
                'must_include': ['glob', 'file_read'],
                'avoid': ['run_command'],
                'max_calls': 3,
            },
        },
        'list-directory': {
            'description': 'List a directory tree',
            'task': 'List the contents of the project directory.',
            'files': {
                'src/app.py': 'x = 1\n',
                'docs/readme.md': '# Project\n',
            },
            'expected': ['list_dir'],
            'verifier': {
                'must_include': ['list_dir'],
                'avoid': ['run_command'],
                'max_calls': 2,
            },
        },
        'grep-symbol': {
            'description': 'Find where a symbol is defined',
            'task': 'Find where the function run_loop is defined in this project.',
            'files': {
                'src/app.py': (
                    'import os\n'
                    '\n'
                    'def run_loop():\n'
                    '    return 0\n'
                ),
                'src/util.py': 'helper = 1\n',
            },
            'expected': ['grep'],
            'verifier': {
                'must_include': ['grep'],
                'avoid': ['run_command'],
                'max_calls': 2,
            },
        },
        'page-large-file': {
            'description': 'Page through a large file with offset/limit',
            'task': 'Read src/big.txt fully and report the text on its final line.',
            'files': {
                'src/big.txt': _large_file(),
            },
            'expected': ['file_read', 'file_read'],
            'verifier': {
                'must_include': ['file_read'],
                'min_calls': 2,
                'avoid': ['run_command'],
            },
        },
    })