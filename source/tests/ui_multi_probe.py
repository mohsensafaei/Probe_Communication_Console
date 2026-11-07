import json
import gc
import weakref
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
from probe.app import Probe


class MultiProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.patch=patch('probe.app.data_directory',return_value=Path(self.directory.name));self.patch.start()
        self.window=Probe();self.errors=[]
        self.window.report_callback_exception=lambda *e:self.errors.append(e)
        self.window.update()

    def tearDown(self):
        self.window.close();self.patch.stop();self.directory.cleanup()
        self.assertEqual(self.errors,[])

    def spin(self,condition,timeout=5):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.window.update()
            if condition():return
            time.sleep(.005)
        self.fail('Multi-probe operation timed out')

    def connect(self,probe,mode):
        probe.choose_mode(mode)
        if mode=='TCP Server':probe.vars['listen_port'].set('0')
        else:probe.vars['serial_port'].set('loop://')
        probe.toggle();self.spin(lambda:probe.engine.ready)

    def test_plus_independent_settings_and_named_tabs(self):
        first=self.window.current_probe
        self.window.add_button.invoke();self.window.update();second=self.window.current_probe
        self.assertIsNot(first,second);self.assertEqual(len(self.window.probes),2)
        second.vars['port'].set('3456');self.assertNotEqual(first.vars['port'].get(),'3456')
        self.assertIsNot(first.queue,second.queue);self.assertIsNot(first.events,second.events)
        self.assertIsNot(first.terminal.model,second.terminal.model)
        self.assertNotEqual(first.settings_path,second.settings_path)
        with patch('probe.workspaces.simpledialog.askstring',return_value='Service → POS'):self.window.rename_probe()
        self.assertIn('Service → POS',self.window.probe_tabs.tab(second,'text'))
        self.assertEqual([second.notebook.tab(t,'text') for t in second.notebook.tabs()],['Traffic','Live plot','Terminal'])

    def test_simultaneous_tcp_and_serial_hidden_capture_and_close_isolation(self):
        first=self.window.current_probe;second=self.window.new_probe();third=self.window.new_probe()
        self.connect(first,'TCP Server');self.connect(second,'TCP Server');self.connect(third,'USB / Serial')
        path=Path(self.directory.name)/'first.jsonl';first.engine.record(path)
        payloads=[bytes(range(256))*64,b'SERVICE\x00\xff'*1500,b'POS\x00\xff'*1000]
        addresses=[p.engine.server.sockets[0].getsockname()[:2] for p in (first,second)]
        with socket.create_connection(addresses[0],timeout=3) as a,socket.create_connection(addresses[1],timeout=3) as b:
            with patch.object(first.table,'insert',wraps=first.table.insert) as insert:
                a.sendall(payloads[0]);b.sendall(payloads[1]);third.engine.send(payloads[2])
                self.spin(lambda:all(p.rx_total==len(data) for p,data in zip((first,second,third),payloads)))
                self.assertEqual(insert.call_count,0)
            for p,data in zip((first,second,third),payloads):
                self.assertEqual(b''.join(e['data'] for e in p.events.values() if e['direction']=='RX'),data)
            first.engine.record()
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(b''.join(bytes.fromhex(r['hex']) for r in rows if r['kind']=='data'),payloads[0])
            self.window.probe_tabs.select(first);self.window.update()
            self.assertEqual(len(first.table.get_children()),len(first.events))
            self.assertTrue(self.window.close_probe(first));self.assertTrue(second.engine.ready);self.assertTrue(third.engine.ready)
            b.sendall(b'NEXT');third.engine.send(b'NEXT')
            self.spin(lambda:second.rx_total==len(payloads[1])+4 and third.rx_total==len(payloads[2])+4)
        self.assertNotIn(first,self.window.probes)

    def test_shortcut_target_and_probe_timer_lifetime(self):
        first=self.window.current_probe;second=self.window.new_probe()
        for p in (first,second):self.connect(p,'USB / Serial')
        second.payload.delete('1.0','end');second.payload.insert('1.0','SECOND')
        self.window.probe_tabs.select(second);self.window.update()
        self.window._invoke('send');self.spin(lambda:second.engine.rx==6)
        self.assertEqual(first.engine.tx,0)
        called=[];second.after(80,lambda:called.append(True))
        first.after(100,lambda:self.fail('Closed probe timer ran'))
        self.window.close_probe(first);self.spin(lambda:bool(called))
        self.assertTrue(second.engine.ready)

    def test_reopen_reuses_saved_settings_and_closes_owned_windows(self):
        second=self.window.new_probe();second.vars['port'].set('4567')
        popup=second.dialog('Owned window');self.window.update()
        self.window.close_probe(second);self.assertFalse(popup.winfo_exists())
        reopened=self.window.new_probe();self.assertEqual(reopened.slot,2)
        self.assertEqual(reopened.vars['port'].get(),'4567')
        for _ in range(5):
            page=self.window.new_probe();self.window.update();self.window.close_probe(page)
        ref=weakref.ref(page);del page;gc.collect();self.assertIsNone(ref())
        self.assertEqual(len(self.window.probes),2)
        self.window.probe_tabs.select(reopened);self.window.update()
        self.assertEqual(self.window.current_probe,reopened)

    def test_last_close_leaves_one_usable_probe(self):
        self.window.close_probe();self.window.update()
        self.assertEqual(len(self.window.probes),1)
        self.assertFalse(self.window.current_probe.closing)
        self.assertTrue(self.window.current_probe.winfo_ismapped())

    def test_hover_close_targets_background_tab_and_cancelled_press(self):
        first=self.window.current_probe;second=self.window.new_probe()
        self.connect(first,'USB / Serial');self.connect(second,'USB / Serial')
        tabs=self.window.probe_tabs;self.window.update()
        point=None
        for y in range(8,44,4):
            for x in range(8,tabs.winfo_width(),2):
                if tabs.identify(x,y)=='Probe.close' and tabs.index(f'@{x},{y}')==0:point=(x,y);break
            if point:break
        self.assertIsNotNone(point)
        x,y=point;tabs.event_generate('<Motion>',x=x,y=y);self.window.update()
        tabs.event_generate('<ButtonPress-1>',x=x,y=y)
        self.assertIs(self.window.current_probe,second)
        tabs.event_generate('<ButtonRelease-1>',x=0,y=80);self.window.update()
        self.assertEqual(len(self.window.probes),2)
        tabs.event_generate('<ButtonPress-1>',x=x,y=y)
        tabs.event_generate('<ButtonRelease-1>',x=x,y=y);self.window.update()
        self.assertNotIn(first,self.window.probes);self.assertIs(self.window.current_probe,second)
        self.assertTrue(second.engine.ready)
        second.engine.send(b'STILL CONNECTED');self.spin(lambda:second.engine.rx==15)


if __name__=='__main__':unittest.main()
