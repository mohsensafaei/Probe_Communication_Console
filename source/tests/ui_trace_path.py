import gc
from pathlib import Path
import tempfile
import unittest
import weakref
from unittest.mock import patch
from probe.app import Probe


class TraceUITests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.directory=tempfile.TemporaryDirectory()
        self.patch=patch('probe.app.data_directory',return_value=Path(self.directory.name));self.patch.start()
        self.window=Probe();self.errors=[]
        self.window.report_callback_exception=lambda *error:self.errors.append(error)
        self.first=self.window.current_probe;self.second=self.window.new_probe();self.window.update()

    def tearDown(self):
        self.window.close();self.patch.stop();self.directory.cleanup();self.assertEqual(self.errors,[])

    def add(self,probe,data,direction='TX'):
        probe.add_event(dict(kind='data',time=100+len(probe.events),direction=direction,peer='device',data=data))

    def test_changed_id_opens_existing_diff_and_correct_probe_pickers(self):
        self.add(self.first,b'{"sid":"123","amount":100000}')
        self.add(self.second,b'{"sid":"123","amount":10000}')
        self.add(self.second,b'{"sid":"456","amount":10000}')
        trace=self.window.trace_path(self.first);trace.field.set('sid');trace.match();self.window.update()
        self.assertEqual(len(trace.matches),1)
        self.assertEqual(trace.view.item('0','values')[4],'Changed')
        compared=trace.compare();pane=compared.comparison
        self.assertEqual(pane.a,next(iter(self.first.events.values()))['data'])
        self.assertEqual(pane.b,next(iter(self.second.events.values()))['data'])
        self.assertTrue(any(d.kind=='changed' or d.kind=='removed' for d in pane.differences))
        for side,probe in (('A',self.first),('B',self.second)):
            picker=pane.choose(side);self.assertEqual(picker.rows,list(probe.events.values()));picker.destroy()
        self.assertIsNone(self.first.engine);self.assertIsNone(self.second.engine)

    def test_split_stream_matches_and_duplicate_occurrences_require_selection(self):
        self.add(self.first,b'\0\xffABC')
        self.add(self.second,b'prefix\0\xff');self.add(self.second,b'AB');self.add(self.second,b'Csuffix')
        trace=self.window.trace_path(self.first);self.window.update()
        self.assertEqual(trace.view.selection(),('0',))
        self.assertEqual(trace.compare().comparison.b,b'\0\xffABC')
        self.add(self.second,b'\0\xffABC');self.assertEqual(len(trace.matches),1)
        trace.snapshot();self.window.update()
        self.assertEqual(len(trace.matches),2);self.assertEqual(trace.view.selection(),())
        self.assertEqual(str(trace.compare_button.cget('state')),'disabled')

    def test_manual_chunks_missing_and_snapshot_lifecycle(self):
        self.add(self.first,b'ABC');self.add(self.second,b'AX');self.add(self.second,b'C')
        trace=self.window.trace_path(self.first);self.window.update()
        self.assertIn('No match yet',trace.note.get())
        trace.view.selection_set(trace.view.get_children())
        self.assertEqual(trace.compare().comparison.b,b'AXC')
        self.add(self.second,b'ABC');self.assertEqual(len(trace.rows),2)
        trace.snapshot();self.assertEqual(len(trace.matches),1)
        trace.destroy();self.assertIsNone(self.window.trace_window)
        trace=self.window.trace_path(self.first);ref=weakref.ref(trace)
        self.window.close_probe(self.second);self.assertFalse(trace.winfo_exists())
        self.assertIsNone(self.window.trace_window);del trace;gc.collect();self.assertIsNone(ref())

    def test_no_traffic_single_probe_and_invalid_id_are_explained(self):
        self.window.close_probe(self.second)
        trace=self.window.trace_path(self.first)
        self.assertIn('two different probes',trace.feedback.get());trace.destroy()
        self.second=self.window.new_probe()
        trace=self.window.trace_path(self.first)
        self.assertIn('No reference traffic',trace.feedback.get())
        self.add(self.first,b'not JSON');trace.snapshot();trace.field.set('sid');trace.action(trace.match)
        self.assertIn('Identifier not found',trace.feedback.get())

    def test_draft_search_never_filters_and_invalid_submit_keeps_results(self):
        self.window.probe_tabs.select(self.first);self.window.update()
        self.add(self.first,b'\0\xff');self.add(self.first,b'{"sid":"A"}')
        with patch.object(self.first.table,'delete',wraps=self.first.table.delete) as clear:
            for mode in ('Hex bytes','Text','Hex bytes','Text'):
                self.first.vars['search_mode'].set(mode);self.window.update()
                self.assertEqual(len(self.first.table.get_children()),2)
            self.assertEqual(clear.call_count,0)
        self.assertNotIn('search_field',self.first.vars)
        self.first.vars['search'].set('A')
        self.window.update();self.assertEqual(len(self.first.table.get_children()),2)
        self.first.search_button.invoke();self.assertEqual(len(self.first.table.get_children()),1)
        self.first.vars['search'].set('no match');self.window.update()
        self.assertEqual(len(self.first.table.get_children()),1)
        self.first.vars['search_mode'].set('Hex bytes');self.first.vars['search'].set('00 FF');self.first.apply_search()
        self.first.vars['search'].set('A');self.first.apply_search()
        self.assertEqual(len(self.first.table.get_children()),1)
        self.assertEqual(self.first.search_count.cget('text'),'Invalid search')
        self.first.vars['search_mode'].set('Text');self.window.update()
        self.assertEqual(len(self.first.table.get_children()),2)
        self.add(self.first,b'new traffic');self.assertEqual(len(self.first.table.get_children()),3)
        self.first.clear_search();self.first.vars['search'].set('new traffic')
        self.window.focus_force();self.first.search_entry.focus_set();self.window.update()
        self.first.search_entry.event_generate('<Return>');self.window.update()
        self.assertEqual(len(self.first.table.get_children()),1)

    def test_legacy_json_search_preferences_and_profiles_load_as_text(self):
        import json
        path=Path(self.directory.name)/'settings-probe-3.json'
        path.write_text(json.dumps(dict(last=dict(search_mode='JSON field',search_field='sid'))))
        probe=self.window.new_probe();self.assertEqual(probe.vars['search_mode'].get(),'Text')
        self.add(probe,b'raw data');probe.profiles={'Legacy':dict(search_mode='JSON field',search_field='sid',search='missing')}
        probe.vars['profile'].set('Legacy');probe.load_profile();self.window.update()
        self.assertEqual(probe.vars['search_mode'].get(),'Text')
        self.assertEqual(len(probe.table.get_children()),1)


if __name__=='__main__':unittest.main()
