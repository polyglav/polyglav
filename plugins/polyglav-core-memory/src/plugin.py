import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
_added = False
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    _added = True
try:
    import memory as _memory
finally:
    if _added:
        sys.path.remove(str(SRC))


def register_services(services):
    services['memory'] = _memory


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'memorize',
        description='Summarize the run into role, team, or job memory',
        subcommands=[
            ('', 'Memorize the active run into the active role memory'),
            ('<role|team|job> [name]', 'Memorize into a named scope'),
        ])
    def memorize_cmd(arg=''):
        parts = arg.strip().split(maxsplit=1)
        scope = parts[0] if parts else 'role'
        name = parts[1].strip() if len(parts) > 1 else ''
        print(chat.memorize(scope, name))
