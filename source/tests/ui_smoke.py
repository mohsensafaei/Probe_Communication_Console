"""Run with an X display. Captures previews and verifies end-to-end GUI behavior."""
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from probe.app import Probe
from probe.engine import MODES

class UISmoke(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher=patch("probe.app.data_directory",return_value=Path(directory.name))
        patcher.start();self.addCleanup(patcher.stop)
        self.app=Probe();self.errors=[]
        self.app.report_callback_exception=lambda *e:self.errors.append(e)
        self.app.update()

    def tearDown(self):
        self.app.close();self.assertEqual(self.errors,[],self.errors)

    def spin(self,condition,timeout=4):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.app.update()
            if condition():return
            time.sleep(.01)
        self.fail("UI condition timed out")

    def test_modes_dialogs_and_small_window(self):
        for mode in MODES:
            self.app.choose_mode(mode);self.app.update()
            self.assertTrue(self.app.connection_button.winfo_ismapped())
        for fn in (self.app.tools,self.app.framing_dialog,self.app.macro_dialog,self.app.appearance,self.app.help):
            fn();self.app.update()
            for w in self.app.winfo_children():
                if isinstance(w,tk.Toplevel):w.destroy()
        self.app.geometry("1060x740");self.app.update()
        self.assertLess(self.app.send_button.winfo_rooty()+self.app.send_button.winfo_height(),self.app.winfo_rooty()+self.app.winfo_height())
        self.assertTrue(self.app.status.winfo_ismapped())
        self.assertGreaterEqual(self.app.table.winfo_height(),85)

    def test_serial_send_capture_inspector(self):
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"capture.jsonl";self.app.record_path=str(path)
            self.app.vars["reconnect"].set(True)
            self.app.toggle();self.spin(lambda:self.app.engine.ready)
            self.app.vars["send_mode"].set("Hex")
            self.app.payload.delete("1.0","end");self.app.payload.insert("1.0","00 02 03 A4 FF")
            self.assertTrue(self.app.send())
            self.spin(lambda:len(self.app.order)>=2)
            rows=[self.app.events[i] for i in self.app.order]
            self.assertEqual(rows[-1]["data"],bytes.fromhex("00 02 03 A4 FF"))
            self.app.table.selection_set(self.app.order[-1]);self.app.inspect()
            self.assertEqual(len(self.app.byte_table.get_children()),5)
            self.app.pause();self.app.send();self.spin(lambda:len(self.app.order)>=4)
            self.app.pause();self.assertEqual(len(self.app.table.get_children()),4)
            self.app.vars["search"].set("hex:A4 FF");self.app.refresh()
            self.assertEqual(len(self.app.table.get_children()),4)
            self.app.toggle();self.spin(lambda:not self.app.active)
            # Manual stop must not trigger automatic reconnect.
            end=time.monotonic()+1.7
            while time.monotonic()<end:self.app.update();time.sleep(.01)
            self.assertFalse(self.app.active)
            records=[json.loads(s) for s in path.read_text().splitlines()]
            self.assertEqual(sum(1 for r in records if r["kind"]=="data"),4)

    @unittest.skipIf(os.name == "nt", "PTY test requires Linux/POSIX")
    def test_linux_serial_device_duplex_and_reconnect(self):
        import tty
        master, slave = os.openpty()
        tty.setraw(slave)
        os.set_blocking(master, False)
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        self.app.choose_mode("USB / Serial")
        self.app.vars["serial_port"].set(os.ttyname(slave))
        self.app.toggle()
        self.spin(lambda: self.app.engine.ready)
        wire = bytes(range(256))
        os.write(master, wire)
        self.spin(lambda: self.app.engine.rx == len(wire) and bool(self.app.order))
        captured = b"".join(e["data"] for e in self.app.events.values() if e["direction"] == "RX")
        self.assertEqual(captured, wire)
        self.app.engine.send(wire)
        self.spin(lambda: self.app.engine.tx == len(wire))
        self.assertEqual(os.read(master, len(wire)), wire)
        self.app.toggle()
        self.spin(lambda: not self.app.active)
        self.app.engine.join()
        self.app.toggle()
        self.spin(lambda: self.app.engine.ready)
        os.write(master, b"reconnected")
        self.spin(lambda: self.app.engine.rx == len(b"reconnected"))

    def test_inspector_pages_reach_every_byte(self):
        data=bytes(range(256))*40
        self.app.add_event(dict(kind="data",time=time.time(),direction="RX",peer="test",data=data))
        self.app.table.selection_set(self.app.order[-1]);self.app.select_event()
        self.assertEqual(len(self.app.byte_table.get_children()),4096)
        self.app.change_page(1)
        self.assertEqual(self.app.inspector_offset,4096)
        self.assertTrue(self.app.byte_table.exists("b4096"))
        self.app.change_page(1)
        self.assertEqual(len(self.app.byte_table.get_children()),2048)
        self.assertTrue(self.app.byte_table.exists("b10239"))

    def test_live_terminal_preserves_raw_capture(self):
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        self.app.notebook.select(4)
        wire=b"\x1b[31mRED\x1b[0m\r\nREADY> "
        self.app.engine.send(wire)
        self.spin(lambda:"READY>" in "".join(self.app.terminal.model.screen.display))
        self.assertEqual(self.app.events[self.app.order[-1]]["data"],wire)
        self.assertEqual(self.app.terminal.model.screen.buffer[0][0].fg,"red")
        self.app.terminal.keyboard.set(True)
        self.app.terminal.key(SimpleNamespace(keysym="c",char="\x03",state=4))
        self.spin(lambda:any(e["direction"]=="TX" and e["data"]==b"\x03" for e in self.app.events.values()))
        self.app.terminal.pop_out();self.app.update()
        self.assertIs(self.app.terminal_popout_pane.model,self.app.terminal.model)
        self.app.terminal_popup.destroy()

    def test_import_then_replay_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"traffic.jsonl"
            rows=[dict(kind="data",time=1,direction="TX",peer="test",hex="0002A4FF"),dict(kind="data",time=1.05,direction="TX",peer="test",hex="0306")]
            path.write_text("\n".join(json.dumps(r) for r in rows))
            self.app.import_capture(path)
            self.assertEqual(len(self.app.order),2)
            self.assertIsNone(self.app.engine)
            self.app.table.selection_set(self.app.order[0]);self.app.load_selected_payload()
            self.assertEqual(self.app.payload_bytes(),bytes.fromhex("00 02 A4 FF"))
            self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
            self.app.toggle();self.spin(lambda:self.app.engine.ready)
            self.app.start_replay(self.app.last_capture,speed=2)
            self.spin(lambda:sum(len(e["data"]) for e in self.app.events.values() if e["direction"]=="RX")==6)
            self.assertEqual(self.app.engine.rx,6)
            captured=b"".join(e["data"] for e in self.app.events.values() if e["direction"]=="RX")
            self.assertEqual(captured,bytes.fromhex("00 02 A4 FF 03 06"))

    def test_sequence_loop_and_counter_reset(self):
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        base=dict(send_mode="Text",encoding="ascii",ending="None",checksum="None",prefix="",suffix="")
        self.app.macros=[dict(base,name="First",text="A"),dict(base,name="Second",text="B")]
        self.app.vars["sequence_loop"].set(True);self.app.vars["interval"].set("50")
        self.app.run_sequence();self.spin(lambda:sum(len(e["data"]) for e in self.app.events.values() if e["direction"]=="TX")>=4 and sum(len(e["data"]) for e in self.app.events.values() if e["direction"]=="RX")>=4)
        self.app.stop_sequence();self.spin(lambda:self.app.engine.tx==self.app.engine.rx)
        sent=b"".join(e["data"] for e in self.app.events.values() if e["direction"]=="TX")
        self.assertTrue(sent.startswith(b"ABAB"))
        self.app.reset_counters();self.spin(lambda:self.app.engine.rx==0 and self.app.engine.tx==0)
        self.app.engine.send(b"\xff");self.spin(lambda:self.app.engine.rx==1)
        self.assertEqual(self.app.engine.tx,1)

if __name__=="__main__":unittest.main()
