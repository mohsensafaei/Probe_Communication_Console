import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from probe.settings import BOOL_DEFAULTS, DEFAULTS, read_settings, write_settings
from probe.transports.config import display_framer, validate


class StructureTests(unittest.TestCase):
    def test_core_and_cli_import_without_tk(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import probe.cli, probe.settings, probe.engine, probe.transports.config; "
            "assert 'tkinter' not in sys.modules"], check=True)

    def test_core_does_not_import_presentation(self):
        root=Path(__file__).resolve().parents[1]/'probe'
        for path in root.glob('*.py'):
            if path.name in ('app.py', 'cli.py', '__main__.py'):continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[0], ('ui','tkinter'), str(path))

    def test_settings_roundtrip_preserves_profiles_and_boolean_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            last=DEFAULTS|BOOL_DEFAULTS|{'host':'آزمایش'}
            profiles={'Bench':last};macros=[{'name':'Test','text':'00 FF'}]
            write_settings(path,last,profiles,macros)
            self.assertEqual(read_settings(path),dict(version=1,last=last,profiles=profiles,macros=macros))
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_configuration_validation_is_independent_of_widgets(self):
        config=DEFAULTS|BOOL_DEFAULTS
        validate(config)
        self.assertEqual(display_framer(config).mode,'Chunks')
        for values in ({'port':'0'}, {'host':''}, {'framing':'Fixed length','frame_size':'0'}):
            with self.assertRaises(ValueError):validate(config|values)
