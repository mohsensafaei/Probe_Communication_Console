from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from probe.app import Probe


class EvidenceUI(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.settings=patch('probe.app.data_directory',return_value=Path(self.directory.name));self.settings.start()
        self.window=Probe();self.app=self.window.current_probe;self.errors=[]
        self.window.report_callback_exception=lambda *e:self.errors.append(e)
        self.window.update()
        for direction,data in (('TX',b'one'),('RX',b'two')):
            self.app.add_event(dict(kind='data',time=1,direction=direction,peer='device',data=data))
        self.window.update()

    def tearDown(self):
        self.window.close();self.settings.stop();self.directory.cleanup()
        self.assertEqual(self.errors,[])

    def test_copy_and_find_exact_id_through_filters_and_pause(self):
        selection=tuple(self.app.events.items())
        self.app.copy_event_ids(selection)
        self.assertEqual(self.window.clipboard_get(),'\n'.join(e['event_id'] for _,e in selection))
        key,row=selection[-1]
        self.app.vars['direction'].set('TX');self.app.pause()
        self.app.vars['search'].set('absent');self.app.apply_search()
        self.assertEqual(self.app.find_event_id(row['event_id']),key)
        self.assertEqual(self.app.table.selection(),(key,))
        self.app.analyze();self.assertIn(row['event_id'],self.app.analysis_window.source.get())
        with patch('probe.ui.traffic.messagebox.showinfo') as info:
            self.assertIsNone(self.app.find_event_id('not-retained'));info.assert_called_once()
