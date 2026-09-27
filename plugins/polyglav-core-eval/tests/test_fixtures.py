import importlib.util
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyglav.eval import EvalFixture, verify_fixture


def _load_plugin(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


eval_plugin = _load_plugin('polyglav_eval_plugin', SRC / 'plugin.py')


class TestEvalFixtures(unittest.TestCase):

    def test_register_fixtures_populates_catalog(self):
        fixtures = {}
        eval_plugin.register_fixtures(fixtures)
        self.assertEqual(len(fixtures), 5)

    def test_fixtures_load_and_are_consistent(self):
        fixtures = {}
        eval_plugin.register_fixtures(fixtures)
        for fid, data in fixtures.items():
            fixture = EvalFixture.from_dict(data, id=fid)
            self.assertEqual(fixture.id, fid)
            self.assertTrue(fixture.task)
            for rel in fixture.files:
                self.assertFalse(rel.startswith('.polyglav'), rel)
                self.assertTrue(fixture.files[rel])
            self.assertTrue(fixture.expected)
            self.assertTrue(verify_fixture(fixture, list(fixture.expected), []), fid)


if __name__ == '__main__':
    unittest.main()