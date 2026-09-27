import tempfile
from pathlib import Path

from polyglav.config import Config

_GLOBAL_TEST_HOME = tempfile.mkdtemp(prefix='polyglav-test-global-')
Config.GLOBAL_DIR = Path(_GLOBAL_TEST_HOME)