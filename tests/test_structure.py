import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from probe.resources import resource_root
from probe.settings import BOOL_DEFAULTS, DEFAULTS, data_directory, read_settings, write_settings
from probe.transports.config import display_framer, validate


class StructureTests(unittest.TestCase):
    def test_core_and_cli_import_without_tk(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import probe.cli, probe.settings, probe.transports.engine, probe.transports.config; "
            "assert 'tkinter' not in sys.modules"], check=True)

    def test_core_does_not_import_presentation(self):
        root=Path(__file__).resolve().parents[1]/'src'/'probe'
        for path in root.rglob('*.py'):
            if 'ui' in path.relative_to(root).parts:continue
            if path.name in ('app.py', 'cli.py', '__main__.py'):continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
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

    def test_data_directory_is_user_scoped_or_explicitly_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            with patch.dict('os.environ', {'LOCALAPPDATA':str(base),'PROBE_DATA_DIR':''}):
                self.assertEqual(data_directory(),base/'Probe')
            with patch.dict('os.environ', {'PROBE_DATA_DIR':str(base/'custom'/'data')}):
                self.assertEqual(data_directory(),base/'custom'/'data')
                self.assertTrue((base/'custom'/'data').is_dir())

    def test_frozen_data_directory_stays_beside_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            executable=Path(directory)/'Probe.exe'
            with patch.dict('os.environ', {'PROBE_DATA_DIR':''}), patch.object(sys,'frozen',True,create=True), patch.object(sys,'executable',str(executable)):
                self.assertEqual(data_directory(),executable.parent/'probe-data')

    def test_resources_are_independent_of_working_directory(self):
        self.assertTrue((resource_root()/'assets'/'probe.png').is_file())
        self.assertTrue((resource_root()/'drivers'/'windows'/'USBPcapSetup-1.5.4.0.exe').is_file())
        with patch.object(sys,'_MEIPASS','/frozen-resources',create=True):
            self.assertEqual(resource_root(),Path('/frozen-resources'))
