import gc
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from probe.app import Probe

CODE = '''
PLUGIN={'name':'Byte lab','settings':{'gain':2},'actions':['Generate']}
def process(data,c):
 return {'fields':[{'name':'size','value':len(data),'offset':0,'size':len(data)},{'name':'config','value':{'enabled':True}}], 'values':{'size':len(data)*c['settings']['gain']}}
def rebuild(data,fields,c):return str(fields['size']).encode()
def action(name,data,c):return b'GENERATED'
def transform(data,c):return data.upper()
'''


class PluginUITests(unittest.TestCase):
    def setUp(self):
        gc.collect();self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.patcher=patch('probe.app.data_directory',return_value=self.base);self.patcher.start()
        self.window=Probe();self.app=self.window.current_probe;self.errors=[]
        self.window.report_callback_exception=lambda *e:self.errors.append(e)
        self.window.update()

    def tearDown(self):
        worker=self.app.plugins.worker;self.window.close()
        if worker and worker.thread:worker.thread.join(3)
        self.patcher.stop();self.temp.cleanup();self.assertEqual(self.errors,[])

    def spin(self,condition):
        until=time.monotonic()+8
        while time.monotonic()<until:
            self.window.update()
            if condition():return
            time.sleep(.01)
        self.fail('Plugin UI operation timed out')

    def install(self,code=CODE,changes=False):
        path=self.base/'plugin.py';path.write_text(code)
        dialog=self.app.plugins.open()
        with patch('probe.ui.plugin.filedialog.askopenfilename',return_value=str(path)):dialog.add()
        self.window.update();self.assertEqual(len(dialog.entries),1)
        self.assertFalse(dialog.entries[0]['enabled']);self.assertIsNone(self.app.plugins.worker)
        dialog.enabled.set(True);dialog.changes.set(changes);dialog.edit();dialog.apply()
        self.spin(lambda:not self.app.plugins.callbacks)

    def test_live_results_field_edit_rebuild_action_and_plot_share_existing_views(self):
        self.install();self.app.choose_mode('USB / Serial');self.app.vars['serial_port'].set('loop://');self.app.toggle()
        self.spin(lambda:self.app.engine.ready);self.app.engine.send(b'abc')
        self.spin(lambda:len(self.app.plugins.results)==2)
        self.assertEqual([e['data'] for e in self.app.events.values()],[b'abc',b'abc'])
        self.app.table.selection_set(self.app.order[-1]);win=self.app.analyze('Plugins');self.window.update();pane=win.plugins
        self.assertEqual(win.tabs.tab(win.tabs.select(),'text'),'Plugins')
        self.assertEqual(pane.view.item('0','values')[1],'3')
        samples=sum(len(p['rows']) for m in self.app.plot.plugin_models.values() for p in m.peers.values())
        pane.run();self.spin(lambda:not self.app.plugins.inflight)
        self.assertEqual(samples,sum(len(p['rows']) for m in self.app.plot.plugin_models.values() for p in m.peers.values()))
        pane.view.selection_set('1')
        with patch('probe.ui.plugin.simpledialog.askstring',return_value='{"enabled":false}') as ask:
            pane.edit();self.assertEqual(ask.call_args.kwargs['initialvalue'],'{"enabled": true}')
        self.assertEqual(pane.fields[1]['value'],{'enabled':False})
        pane.view.selection_set('0')
        with patch('probe.ui.plugin.simpledialog.askstring',return_value='42'):pane.edit()
        pane.rebuild();self.spin(lambda:pane.output==b'42');pane.load()
        self.assertEqual(self.app.payload_bytes(),b'42')
        self.assertEqual(pane.view.item('0','values')[1],'42')
        pane.preview();self.assertEqual(win.comparison.a,b'abc');self.assertEqual(win.comparison.b,b'42')
        win.tabs.select(pane);pane.view.selection_set('0')
        with patch('probe.ui.plugin.simpledialog.askstring',return_value='43'):pane.edit()
        self.assertIsNone(pane.output)
        pane.action();self.spin(lambda:pane.output==b'GENERATED')
        self.assertEqual(self.app.engine.tx,3)
        source=next(iter(self.app.plot.plugin_models));self.app.plot.mode.set(source);self.app.plot.change_mode()
        self.app.notebook.select(self.app.plot);self.window.update();self.app.plot.render(force=True)
        self.assertTrue(self.app.plot.canvas.find_withtag('curve'))
        self.assertIn('6',self.app.plot.status.get())

    def test_allow_changes_is_explicit_and_captured_original_is_preserved(self):
        self.install(changes=True)
        self.app.choose_mode('USB / Serial');self.app.vars['serial_port'].set('loop://');self.app.toggle()
        self.spin(lambda:self.app.engine.ready);self.app.engine.send(b'abc')
        self.spin(lambda:self.app.rx_total==3)
        tx=next(e for e in self.app.events.values() if e['direction']=='TX')
        self.assertEqual(tx['data'],b'ABC');self.assertEqual(tx['original_hex'],b'abc'.hex())
        self.assertIn('[Modified]',self.app.table.item(self.app.order[0],'values')[-1])
        dialog=self.app.plugins.open();dialog.apply()
        self.assertIn('Disconnect',dialog.feedback.get());self.assertTrue(self.app.engine.ready)

    def test_missing_plugin_does_not_prevent_opening_a_probe(self):
        self.install(changes=True);worker=self.app.plugins.worker
        Path(worker.entries[0]['path']).unlink()
        self.app.save_settings();self.window.close();self.window=Probe();self.app=self.window.current_probe
        self.window.report_callback_exception=lambda *e:self.errors.append(e)
        self.window.update();self.assertIsNone(self.app.plugins.worker)
        self.assertIn('Plugins unavailable',self.app.status.cget('text'))
        self.app.choose_mode('USB / Serial');self.app.vars['serial_port'].set('loop://');self.app.toggle()
        self.assertFalse(self.app.active);self.assertIn('Fix or disable',self.app.status.cget('text'))


if __name__=='__main__':unittest.main()
