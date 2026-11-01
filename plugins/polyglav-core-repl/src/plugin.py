import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
_added = False
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    _added = True
try:
    import chat as _chat
finally:
    if _added:
        sys.path.remove(str(SRC))


def register_frontends(frontends):
    frontends.register(
        'repl',
        lambda config, plugin_manager: _chat.ChatLoop(
            config, plugin_manager=plugin_manager),
        'Terminal REPL')


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register('clear',
                       description='Clear the screen and reprint the header')
    def clear_cmd(_=None):
        chat.redraw()
