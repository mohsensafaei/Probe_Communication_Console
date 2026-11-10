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

    def test_analysis_report_contains_selected_identity_and_never_sends(self):
        import json
        key=next(iter(self.app.events));self.app.table.selection_set(key)
        self.app.analyze();pane=self.app.analysis_window
        path=Path(self.directory.name)/'analysis.json'
        with patch('probe.ui.analysis.filedialog.asksaveasfilename',return_value=str(path)):
            pane.save_analysis()
        report=json.loads(path.read_text())
        self.assertEqual(report['event_id'],self.app.events[key]['event_id'])
        self.assertEqual(report['byte_count'],3);self.assertIsNone(self.app.engine)

    def spin(self,predicate):
        import time
        stop=time.monotonic()+5
        while time.monotonic()<stop:
            self.window.update()
            if predicate():return
            time.sleep(.01)
        self.fail('Evidence preview timed out')

    def test_case_preview_copy_save_and_invalidation_are_local_and_exact(self):
        import json
        import zipfile
        key=next(iter(self.app.events));self.app.table.selection_set(key)
        dialog=self.app.share_case();self.spin(lambda:not dialog.busy)
        self.assertEqual(len(dialog.case['events']),1)
        dialog.context.set('1');self.assertIsNone(dialog.case)
        self.assertTrue(dialog.copy_button.instate(['disabled']))
        dialog.problem.insert('1.0','Wrong reply');self.window.update()
        dialog.preview();self.spin(lambda:not dialog.busy)
        self.assertEqual(len(dialog.case['events']),2)
        dialog.copy();self.assertIn('Wrong reply',self.window.clipboard_get())
        path=Path(self.directory.name)/'case.zip'
        with patch('probe.ui.evidence.filedialog.asksaveasfilename',return_value=str(path)):dialog.save()
        with zipfile.ZipFile(path) as archive:
            rows=[json.loads(line) for line in archive.read('traffic.jsonl').splitlines()]
            self.assertEqual([e['hex'] for e in rows],['6F6E65','74776F'])
        self.assertIsNone(self.app.engine);dialog.window.destroy()

    def test_case_other_probes_are_opt_in_and_masked_copy_is_separate(self):
        second=self.window.new_probe();second.add_event(dict(kind='data',time=2,direction='RX',peer='other',data=b'secret'))
        second.table.selection_set(next(iter(second.events)))
        self.app.table.selection_set(next(iter(self.app.events)))
        dialog=self.app.share_case();self.spin(lambda:not dialog.busy)
        self.assertEqual(len(dialog.case['probes']),1)
        dialog.others.set(True);dialog.masks.insert('1.0','secret');self.window.update()
        dialog.preview();self.spin(lambda:not dialog.busy)
        self.assertEqual(len(dialog.case['probes']),2)
        self.assertEqual(dialog.case['events'][-1]['hex'],'2A'*6)
        self.assertEqual(next(iter(second.events.values()))['data'],b'secret')
        dialog.context.set('bad')
        dialog.action(dialog.preview);self.assertIsNone(dialog.case)
        dialog.window.destroy()

    def test_changed_options_while_building_cannot_enable_stale_copy(self):
        from probe.evidence.case import build_case
        import threading
        started=threading.Event();release=threading.Event()
        def slow(*args):
            started.set();release.wait(3);return build_case(*args)
        self.app.table.selection_set(next(iter(self.app.events)))
        with patch('probe.ui.evidence.build_case',side_effect=slow):
            dialog=self.app.share_case();self.assertTrue(started.wait(1))
            dialog.context.set('1');release.set();self.spin(lambda:not dialog.busy)
        self.assertIsNone(dialog.case);self.assertTrue(dialog.save_button.instate(['disabled']))
        dialog.window.destroy()
