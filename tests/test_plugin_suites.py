import unittest

from polyglav.plugins.manager import PluginManager, load_plugin_test_suite


def load_tests(loader, standard_tests, pattern):
    bundled = PluginManager._bundled_dir()
    for entry in sorted(bundled.iterdir()):
        tests_dir = entry / 'tests'
        if not tests_dir.is_dir():
            continue
        standard_tests.addTests(load_plugin_test_suite(entry))
    return standard_tests