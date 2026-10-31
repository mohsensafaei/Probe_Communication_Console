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
from tkinter import ttk
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

    def click_main_tab(self,title):
        self.app.focus_force();self.app.update()
        wanted=next(i for i,tab in enumerate(self.app.notebook.tabs()) if self.app.notebook.tab(tab,"text")==title)
        for x in range(5,self.app.notebook.winfo_width(),5):
            try:index=self.app.notebook.index(f"@{x},10")
            except tk.TclError:continue
            if index==wanted:
                self.app.notebook.event_generate("<Button-1>",x=x,y=10)
                self.app.notebook.event_generate("<ButtonRelease-1>",x=x,y=10)
                self.app.update();self.assertEqual(self.app.notebook.index(self.app.notebook.select()),wanted);return
        self.fail("Tab is not clickable: "+title)

    def selection_fixture(self):
        for index,data in enumerate((b"OLD",b"A\x00\xff",b"NOT SELECTED",b"B\x00\xfe")):
            self.app.add_event(dict(kind="data",time=time.time()+index/100,direction="TX" if index%2 else "RX",peer="device",data=data))
        self.app.update();return tuple(self.app.order)

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from UISmoke.descendants(child)

    def test_ctrl_click_multiselect_and_refresh_keep_selection(self):
        ids=self.selection_fixture();self.app.focus_force();self.app.table.focus_set()
        def click(key,state=0):
            x,y,w,h=self.app.table.bbox(key,"payload")
            self.app.table.event_generate("<Button-1>",x=x+5,y=y+h//2,state=state)
            self.app.table.event_generate("<ButtonRelease-1>",x=x+5,y=y+h//2,state=state);self.app.update()
        click(ids[0]);click(ids[2],4);click(ids[3],4)
        self.assertEqual(set(self.app.table.selection()),{ids[0],ids[2],ids[3]})
        self.assertFalse(hasattr(self.app,"analysis_window"))
        click(ids[2],4);self.assertEqual(set(self.app.table.selection()),{ids[0],ids[3]})
        self.app.vars["view"].set("Hex");self.app.refresh();self.app.update()
        self.assertEqual(set(self.app.table.selection()),{ids[0],ids[3]})
        self.app.pause();self.app.pause();self.assertEqual(set(self.app.table.selection()),{ids[0],ids[3]})
        click(ids[1]);self.assertEqual(self.app.table.selection(),(ids[1],))
        self.assertFalse(hasattr(self.app,"analysis_window"))

    def test_context_menu_preserves_multiselect_and_targets_unselected_row(self):
        ids=self.selection_fixture();self.app.table.selection_set((ids[1],ids[3]))
        def right_click(key):
            x,y,w,h=self.app.table.bbox(key,"payload")
            with patch("tkinter.Menu.tk_popup"):
                self.app.table.event_generate("<Button-3>",x=x+5,y=y+h//2);self.app.update()
        right_click(ids[3]);menu=self.app._traffic_popup
        self.assertEqual(self.app.table.selection(),(ids[1],ids[3]))
        self.assertEqual(menu.entrycget(0,"label"),"Capture Diff…")
        self.assertEqual(menu.entrycget(1,"label"),"Export selected (2)…");self.assertEqual(menu.index("end"),1)
        right_click(ids[2]);self.assertEqual(self.app.table.selection(),(ids[2],))
        self.assertEqual(self.app._traffic_popup.entrycget(1,"label"),"Export selected (1)…")
        self.assertFalse(hasattr(self.app,"analysis_window"))

    def test_capture_diff_compares_exact_pair_and_keeps_main_selection(self):
        ids=self.selection_fixture();self.app.table.selection_set((ids[3],ids[1]))
        menu=self.app.make_traffic_menu(self.app.selected_traffic());menu.invoke(0);self.app.update()
        window=self.app.analysis_window;pane=window.comparison
        self.assertEqual(window.tabs.tab(window.tabs.select(),"text"),"Capture Diff")
        self.assertEqual(pane.a,b"A\x00\xff");self.assertEqual(pane.b,b"B\x00\xfe")
        self.assertEqual(window.data,pane.b);self.assertIn("#"+ids[1],pane.a_label.get())
        self.assertEqual(self.app.table.selection(),(ids[1],ids[3]));self.assertIsNone(self.app.engine)
        # Re-opening the same pair must not substitute the unselected previous RX row.
        window.hide();menu.invoke(0);self.assertIs(self.app.analysis_window,window)
        self.assertEqual(pane.a,b"A\x00\xff");menu.destroy()

    def test_capture_diff_picker_only_offers_selected_messages(self):
        ids=self.selection_fixture();self.app.table.selection_set((ids[0],ids[1],ids[3]))
        picker=self.app.compare_selected();self.app.update()
        combos=[w for w in self.descendants(picker) if isinstance(w,ttk.Combobox)]
        values=combos[0].cget("values")
        self.assertEqual(len(values),3);self.assertFalse(any(label.startswith("#"+ids[2]+" ·") for label in values))
        picker.message.set(picker.reference.get());self.assertTrue(picker.confirm.instate(["disabled"]))
        picker.message.set(values[2]);picker.confirm.invoke();self.app.update()
        self.assertEqual(self.app.analysis_window.comparison.a,b"OLD")
        self.assertEqual(self.app.analysis_window.comparison.b,b"B\x00\xfe")
        self.assertEqual(len(self.app.table.selection()),3)

    def test_selected_export_snapshot_formats_and_exact_binary_payloads(self):
        import csv
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ("jsonl","csv","txt"):
                with self.subTest(format=suffix):
                    self.app.MAX_ROWS=2000;self.app.clear();ids=self.selection_fixture()
                    self.app.table.selection_set((ids[3],ids[1]))
                    menu=self.app.make_traffic_menu(self.app.selected_traffic());menu.invoke(1)
                    win=next(w for w in self.app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=="Export selected traffic")
                    # Live retention/selection changes cannot expand or invalidate this export.
                    self.app.MAX_ROWS=1
                    self.app.add_event(dict(kind="data",time=time.time(),direction="RX",peer="new",data=b"ARRIVED LATER"))
                    save=next(w for w in self.descendants(win) if isinstance(w,ttk.Button) and w.cget("text")=="Save…")
                    path=Path(folder)/("selected."+suffix)
                    with patch("probe.app.filedialog.asksaveasfilename",return_value=str(path)):save.invoke()
                    if suffix=="jsonl":
                        rows=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                        self.assertEqual([bytes.fromhex(row["hex"]) for row in rows],[b"A\x00\xff",b"B\x00\xfe"])
                        self.assertTrue(all("text" in row for row in rows))
                    elif suffix=="csv":
                        with path.open(encoding="utf-8",newline="") as f:rows=list(csv.DictReader(f))
                        self.assertEqual([bytes.fromhex(row["hex"]) for row in rows],[b"A\x00\xff",b"B\x00\xfe"])
                    else:
                        text=path.read_text(encoding="utf-8")
                        self.assertEqual(text.count("Hex:"),2);self.assertIn("41 00 FF",text);self.assertIn("42 00 FE",text)
                        self.assertNotIn("NOT SELECTED",text);self.assertNotIn("ARRIVED LATER",text)
                    self.assertIn("2 selected messages",self.app.status.cget("text"));menu.destroy()

    def test_export_choices_still_apply_and_toolbar_export_stays_global(self):
        ids=self.selection_fixture();self.app.table.selection_set((ids[1],ids[3]))
        with tempfile.TemporaryDirectory() as folder:
            win=self.app.export(rows=[row for _,row in self.app.selected_traffic()]);self.app.update()
            checks={w.cget("text"):w for w in self.descendants(win) if isinstance(w,ttk.Checkbutton)}
            save=next(w for w in self.descendants(win) if isinstance(w,ttk.Button) and w.cget("text")=="Save…")
            checks["Hex"].invoke();checks["Decoded text"].invoke();self.assertTrue(save.instate(["disabled"]))
            checks["Decoded text"].invoke();path=Path(folder)/"text.jsonl"
            with patch("probe.app.filedialog.asksaveasfilename",return_value=str(path)):save.invoke()
            rows=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows),2);self.assertTrue(all("text" in row and "hex" not in row for row in rows))
            win=self.app.export();save=next(w for w in self.descendants(win) if isinstance(w,ttk.Button) and w.cget("text")=="Save…")
            path=Path(folder)/"all.jsonl"
            with patch("probe.app.filedialog.asksaveasfilename",return_value=str(path)):save.invoke()
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()),4)

    def test_double_click_row_opens_one_analysis_window_with_all_message_views(self):
        self.assertEqual([self.app.notebook.tab(tab,"text") for tab in self.app.notebook.tabs()],["Traffic","Live plot","Terminal"])
        for i,data in enumerate((b"FIRST\0\xff",b"SECOND\r\n")):
            self.app.add_event(dict(kind="data",time=time.time()+i,direction="RX",peer="COM34",data=data))
        self.app.table.selection_set(self.app.order[0]);self.app.update()
        self.assertFalse(hasattr(self.app,"analysis_window"))
        def click(iid):
            self.app.table.see(iid);self.app.update();x,y,w,h=self.app.table.bbox(iid,"payload")
            self.app.table.event_generate("<Button-1>",x=x+5,y=y+h//2)
            self.app.table.event_generate("<ButtonRelease-1>",x=x+5,y=y+h//2);self.app.update()
        self.assertTrue(self.app.table.bind("<Double-1>"))
        self.assertFalse(self.app.table.bind("<ButtonRelease-1>"))
        click(self.app.order[0]);self.assertFalse(hasattr(self.app,"analysis_window"))
        self.app.traffic_clicked(SimpleNamespace(x=self.app.table.bbox(self.app.order[0],"payload")[0]+5,y=self.app.table.bbox(self.app.order[0],"payload")[1]+5));win=self.app.analysis_window
        self.assertEqual(win.data,b"FIRST\0\xff")
        self.assertEqual(win.tabs.tab(win.tabs.select(),"text"),"Decoded text")
        self.assertIn("FIRST",win.payload.decoded.get("1.0","end"))
        self.assertIn("46 49 52 53 54 00 FF",win.payload.hextext.get("1.0","end"))
        win.tabs.select(win.payload.pages["Hex + ASCII"])
        click(self.app.order[1]);self.app.traffic_clicked(SimpleNamespace(x=self.app.table.bbox(self.app.order[1],"payload")[0]+5,y=self.app.table.bbox(self.app.order[1],"payload")[1]+5));self.assertIs(self.app.analysis_window,win)
        self.assertEqual(win.data,b"SECOND\r\n")
        self.assertEqual(win.tabs.tab(win.tabs.select(),"text"),"Hex + ASCII")
        self.app.table.selection_set(self.app.order[0]);self.app.refresh();self.app.update()
        self.assertEqual(win.data,b"SECOND\r\n")
        win.copy_hex();self.assertEqual(self.app.clipboard_get(),b"SECOND\r\n".hex(" ").upper())
        win.load_composer();self.assertEqual(self.app.payload_bytes(),b"SECOND\r\n")
        self.assertIsNone(self.app.engine)

    def test_plot_and_terminal_tabs_click_and_work_over_serial_loop(self):
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        self.click_main_tab("Live plot")
        self.assertTrue(self.app.plot.canvas.winfo_ismapped())
        self.app.engine.send(b"1,2\n3,4\n")
        self.spin(lambda:bool(self.app.plot.canvas.find_withtag("curve")))
        self.assertIn("2 samples",self.app.plot.status.get())
        self.assertEqual(list(self.app.plot.model.peers["loop://"]["rows"]),[(1,2),(3,4)])
        self.click_main_tab("Terminal")
        self.assertTrue(self.app.terminal.text.winfo_ismapped())
        self.assertTrue(self.app.composer.winfo_ismapped());self.assertTrue(self.app.target_combo.winfo_ismapped())
        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Button):yield child
                yield from buttons(child)
        for button in buttons(self.app.terminal):self.assertTrue(button.winfo_ismapped(),button.cget("text"))
        self.assertIn("View only",self.app.terminal.hint.cget("text"))
        self.app.terminal.keyboard_check.invoke();self.app.update()
        self.assertEqual(self.app.focus_get(),self.app.terminal.text)
        self.app.terminal.text.event_generate("<KeyPress>",keysym="k")
        self.spin(lambda:any(e["direction"]=="TX" and e["data"]==b"k" for e in self.app.events.values()))
        self.spin(lambda:"k" in "".join(self.app.terminal.model.screen.display))
        self.assertIn("Send keyboard ON",self.app.terminal.hint.cget("text"))
        self.click_main_tab("Traffic")
        self.assertTrue(self.app.table.winfo_ismapped());self.assertFalse(hasattr(self.app,"analysis_window"))

    def test_terminal_serial_bridge_receives_with_explicit_tcp_client_selected(self):
        import socket
        self.app.choose_mode("Serial ↔ TCP");self.app.vars["serial_port"].set("loop://");self.app.vars["listen_port"].set("0")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        with socket.create_connection(self.app.engine.server.sockets[0].getsockname()[:2],timeout=3) as client:
            self.spin(lambda:len(self.app.engine.clients)==1)
            self.app.vars["target"].set(next(iter(self.app.engine.clients)))
            self.click_main_tab("Terminal");self.app.engine.send(b"BRIDGE READY\r\n")
            self.spin(lambda:"BRIDGE READY" in "".join(self.app.terminal.model.screen.display))
            self.assertEqual(self.app.terminal.peer,"loop://")

    def test_terminal_can_type_to_single_tcp_client_before_first_reply(self):
        import socket
        self.app.choose_mode("TCP Server");self.app.vars["listen_port"].set("0")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        with socket.create_connection(self.app.engine.server.sockets[0].getsockname()[:2],timeout=3) as client:
            self.spin(lambda:len(self.app.engine.clients)==1)
            self.click_main_tab("Terminal");self.app.terminal.keyboard_check.invoke();self.app.update()
            self.app.terminal.text.event_generate("<KeyPress>",keysym="k")
            self.assertEqual(client.recv(1),b"k")
            client.sendall(b"ACK\r\n")
            self.spin(lambda:"ACK" in "".join(self.app.terminal.model.screen.display))
        self.spin(lambda:not self.app.engine.clients)
        self.assertIn("ACK","".join(self.app.terminal.model.screen.display))

    def test_hid_selection_is_unelevated_and_analysis_uses_existing_workspace(self):
        from probe.hid_ui import devices_received
        from probe.hid_reports import HidTracker
        from test_hid import MOUSE,packet
        with patch("probe.hid_helper.launch_helper") as launch:
            self.app.choose_mode("HID Monitor");self.app.update()
            self.assertFalse(self.app.composer.winfo_ismapped())
            self.assertTrue(self.app.terminal.keyboard_check.instate(["disabled"]))
            self.assertTrue(self.app.terminal.paste_button.instate(["disabled"]))
            self.assertEqual(self.app.connection_button.cget("text"),"Start capture")
            launch.assert_not_called()
            self.app.toggle();self.assertFalse(self.app.active);launch.assert_not_called()
        source=r"\\.\USBPcap1:2" if os.name=="nt" else "1:2"
        devices_received(self.app,dict(devices=[dict(name="Lab mouse",source=source)]))
        cfg=self.app.values();self.app.validate(cfg);self.assertEqual(cfg["hid_source"],source)
        event=HidTracker({0:[0x81]},{0:MOUSE.hex()}).consume(packet())
        self.app.add_event(event);self.app.table.selection_set(self.app.order[-1]);win=self.app.analyze();self.app.update()
        self.assertEqual(win.tabs.tab(win.tabs.select(),"text"),"HID Report")
        self.assertEqual(len(win.hid.view.get_children()),6)
        self.app.choose_mode("TCP Client");self.app.update();self.assertTrue(self.app.composer.winfo_ismapped())

    def test_hid_permission_cancel_leaves_normal_app_usable(self):
        from probe.hid_ui import devices_received
        self.app.choose_mode("HID Monitor")
        source=r"\\.\USBPcap1:2" if os.name=="nt" else "1:2"
        devices_received(self.app,dict(devices=[dict(name="Lab mouse",source=source)]))
        with patch("probe.hid_monitor.HelperClient") as helper:
            helper.return_value.messages.side_effect=OSError("Permission request cancelled.")
            self.app.toggle();self.spin(lambda:not self.app.active)
        self.assertIn("cancelled",self.app.status.cget("text"));self.assertTrue(self.app.winfo_exists())
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        self.app.engine.send(b"STILL WORKS");self.spin(lambda:self.app.engine.rx==11)

    def test_modes_dialogs_and_small_window(self):
        for mode in MODES:
            self.app.choose_mode(mode);self.app.update()
            self.assertTrue(self.app.connection_button.winfo_ismapped())
        for fn in (self.app.tools,self.app.framing_dialog,self.app.macro_dialog,self.app.help):
            fn();self.app.update()
            for w in self.app.winfo_children():
                if isinstance(w,tk.Toplevel):w.destroy()
        self.app.choose_mode("TCP Client")
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
            self.app.table.selection_set(self.app.order[-1]);analysis=self.app.analyze()
            self.assertEqual(len(analysis.payload.byte_table.get_children()),5)
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
        self.app.table.selection_set(self.app.order[-1]);pane=self.app.analyze().payload
        self.assertEqual(len(pane.byte_table.get_children()),4096)
        pane.change_page(1)
        self.assertEqual(pane.page,1)
        self.assertTrue(pane.byte_table.exists("b4096"))
        pane.change_page(1)
        self.assertEqual(len(pane.byte_table.get_children()),2048)
        self.assertTrue(pane.byte_table.exists("b10239"))

    def test_live_terminal_preserves_raw_capture(self):
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        self.app.notebook.select(self.app.terminal)
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

    def test_terminal_detaches_and_docks_one_visible_view(self):
        self.app.notebook.select(self.app.terminal);self.app.update()
        self.app.terminal.pop_out();self.app.update()
        self.assertEqual(self.app.notebook.tab(self.app.terminal,"state"),"hidden")
        self.assertFalse(self.app.terminal.winfo_ismapped())
        self.assertTrue(self.app.terminal_popout_pane.winfo_ismapped())
        self.app.terminal.model.feed(b"DETACHED")
        self.app.terminal_popup.destroy();self.app.update()
        self.assertEqual(self.app.notebook.tab(self.app.terminal,"state"),"normal")
        self.assertTrue(self.app.terminal.winfo_ismapped())
        self.assertIn("DETACHED","".join(self.app.terminal.model.screen.display))

    def test_analysis_remembers_tabs_and_comparison_direction(self):
        for direction in ("TX","RX"):
            self.app.add_event(dict(kind="data",direction=direction,peer="device",time=time.time(),data=b'{"temp":25}'))
        self.app.table.selection_set(self.app.order[0]);win=self.app.analyze("Compare");self.app.update()
        pane=win.comparison;picker=pane.choose("A");self.app.update()
        self.assertEqual(picker.direction.get(),"TX")
        picker.direction.set("RX");picker.refresh();picker.destroy();self.app.update()
        picker=pane.choose("A");self.assertEqual(picker.direction.get(),"RX");picker.destroy()
        win.withdraw();self.app.update();self.assertIs(self.app.analyze(),win)
        self.assertEqual(win.tabs.tab(win.tabs.select(),"text"),"Capture Diff")
        self.assertEqual(win.protocol.MODES,("Auto","Raw Bytes"))
        self.app.table.selection_set(self.app.order[1]);self.app.analyze();self.app.update()
        picker=pane.choose("A");self.assertEqual(picker.direction.get(),"RX");picker.destroy()
        win.tabs.select(win.payload.pages["Every byte"]);self.app.update();win.withdraw()
        self.app.analyze();self.app.update();self.assertEqual(win.tabs.tab(win.tabs.select(),"text"),"Every byte")
        self.app.table.selection_set(self.app.order[0]);self.app.analyze();self.app.update()
        picker=pane.choose("A");self.assertEqual(picker.direction.get(),"RX");picker.destroy()
        self.assertEqual(win.tabs.tab(win.tabs.select(),"text"),"Capture Diff")

    def test_traffic_search_filters_full_bytes_values_and_live_rows(self):
        rows=[("RX",b'{"data":{"amount":"10000"}}'),("TX",b'{"data":{"amount":"20000"}}'),("RX",b'X'*900+b'\xA4\xFF'),("RX",b'\x0A\xBC')]
        for direction,data in rows:self.app.add_event(dict(kind="data",direction=direction,peer="device",time=time.time(),data=data))
        self.app.vars["search_mode"].set("Hex bytes");self.app.vars["search"].set("A4FF");self.app.refresh(force=True)
        self.assertEqual(len(self.app.table.get_children()),1);self.assertEqual(len(self.app.order),4)
        self.app.add_event(dict(kind="data",direction="TX",peer="device",time=time.time(),data=b'\xA4\xFF'))
        self.assertEqual(len(self.app.table.get_children()),2)
        self.app.vars["direction"].set("RX");self.app.refresh(force=True);self.assertEqual(len(self.app.table.get_children()),1)
        self.app.vars["direction"].set("All");self.app.vars["search_mode"].set("JSON field");self.app.vars["search_field"].set("data.amount")
        self.app.vars["search"].set("10000");self.app.refresh(force=True)
        self.assertEqual(self.app.table.get_children(),(self.app.order[0],))
        self.app.pause();self.app.vars["search"].set("20000");self.app.refresh(force=True)
        self.assertEqual(self.app.table.get_children(),(self.app.order[1],))
        self.app.vars["search_mode"].set("Hex bytes");self.app.vars["search"].set("A");self.app.refresh(force=True)
        self.assertEqual(len(self.app.table.get_children()),0);self.assertEqual(self.app.search_count.cget("text"),"Invalid search")
        self.app.clear_search();self.assertEqual(len(self.app.table.get_children()),5)
        self.assertEqual(len(self.app.events),5);self.assertFalse(hasattr(self.app,"analysis_window"))
        self.app.vars["search_mode"].set("JSON field");self.app.geometry("1060x700");self.app.update()
        self.assertTrue(self.app.search_fieldbox.winfo_ismapped());self.assertGreater(self.app.search_entry.winfo_width(),60)
        self.assertLessEqual(self.app.search_count.winfo_x()+self.app.search_count.winfo_width(),self.app.searchbar.winfo_width())

    def test_plot_uses_available_height_and_footer_fits_small_window(self):
        self.app.geometry("1060x700");self.app.notebook.select(self.app.plot);self.app.update()
        pane=self.app.plot
        self.assertGreater(pane.canvas.winfo_height(),pane.winfo_height()-85)
        controls=(pane.mode_combo,pane.configure_button,pane.peer_combo,pane.clear_button)
        for widget in controls:
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),pane.controls.winfo_width())
        centers=[widget.winfo_y()+widget.winfo_height()/2 for widget in controls]
        self.assertLessEqual(max(centers)-min(centers),1)

    def test_custom_plot_configuration_on_real_serial_rx(self):
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        plot=self.app.plot;self.app.notebook.select(plot)
        plot.configure_custom();plot.custom_variables["field"].set("data.temp");plot.apply_custom();self.app.update()
        self.assertEqual(plot.mode.get(),"Custom")
        self.app.engine.send(b'{"data":{"temp":12,"voltage":3.3}}')
        self.spin(lambda:bool(plot.canvas.find_withtag("curve")))
        self.assertEqual(plot.model.peers['loop://']['rows'][-1],(12,))
        plot.clear();self.assertEqual(plot.mode.get(),"Custom");self.assertIsNotNone(plot.model.config)
        plot.mode.set("Auto");plot.change_mode();self.assertIsNone(plot.model.config)

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

    def test_lab_layout_and_appearance_button_removed(self):
        win=self.app.test_lab()
        win.geometry("980x680")
        self.app.update()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        self.assertFalse(any(w.cget("text")=="Appearance" for w in descendants(self.app) if isinstance(w,(tk.Button,ttk.Button))))
        for tab in (0,1):
            self.app.testlab_notebook.select(tab);self.app.update()
            buttons=[w for w in descendants(win) if isinstance(w,ttk.Button) and w.winfo_ismapped()]
            for button in buttons:
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),win.winfo_rooty()+win.winfo_height())
        pane=self.app.sequence_panel
        pane.open_editor()
        pane.payload.insert("1.0","GG")
        pane.action(pane.add)
        self.assertIn("Hex",pane.feedback.get())
        self.assertEqual(self.app.macros,[])
        self.assertEqual(pane.payload.get("1.0","end-1c"),"GG")

    @unittest.skipIf(os.name!="posix","Requires Linux PTY")
    def test_lab_capture_to_virtual_device_without_hardware(self):
        import serial
        now=time.time()
        self.app.add_event(dict(kind="data",time=now,direction="TX",peer="device",data=b"QUERY"))
        self.app.add_event(dict(kind="data",time=now+.01,direction="RX",peer="device",data=b"ANSWER"))
        self.app.test_lab()
        pane=self.app.simulator_panel
        pane.use_history()
        self.assertEqual(len(self.app.simulator_model.exchanges),1)
        self.app.vars["simulator_transport"].set("Virtual serial (PTY)")
        pane.start();self.spin(lambda:self.app.engine.ready)
        with serial.Serial(self.app.engine.app_path,115200,timeout=2) as app:
            app.write(b"QU");app.write(b"ERY")
            self.assertEqual(app.read(6),b"ANSWER")
            self.spin(lambda:"requests matched" in self.app.simulator_info.get())
        self.assertEqual(self.app.engine.serials,[])
        pane.stop();self.spin(lambda:not self.app.active)

    def test_lab_sequence_edit_export_import_and_run(self):
        self.app.macro_dialog()
        pane=self.app.sequence_panel
        pane.individual.set(True)
        pane.open_editor()
        pane.fields["name"].set("Binary check")
        pane.fields["delay_ms"].set("3")
        pane.fields["repeat"].set("2")
        pane.fields["expect"].set("00 FF")
        pane.payload.insert("1.0","00 FF")
        pane.add()
        pane.editor.destroy()
        pane.table.selection_set("0");pane.duplicate()
        pane.table.selection_set("1");pane.move(-1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"steps.json"
            self.app.vars["sequence_cycles"].set("2")
            with patch("probe.testlab_ui.filedialog.asksaveasfilename",return_value=str(path)):
                pane.save_file()
            self.app.macros=[]
            with patch("probe.testlab_ui.filedialog.askopenfilename",return_value=str(path)):
                pane.load_file()
            self.assertEqual(len(self.app.macros),2)
            self.assertEqual(self.app.vars["sequence_cycles"].get(),"2")
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        pane.run()
        self.spin(lambda:"Sequence complete" in self.app.sequence_info.get())
        self.assertEqual(self.app.engine.tx,16)
        self.assertIn("8 replies checked",self.app.sequence_info.get())

    def test_sequence_capture_rx_tx_subset_order_and_destination(self):
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.vars["serial_port"].set("COM34")
        self.app.choose_mode("Serial ↔ TCP")
        self.app.vars["side"].set("Device / upstream")
        for n,(direction,data) in enumerate((("RX",b"FIRST\0"),("TX",b"COMMAND"),("RX",b"SECOND"),("RX",b"LAST\xff"))):
            self.app.add_event(dict(kind="data",time=10+n,direction=direction,peer="COM34",data=data))
        picker=pane.use_capture();self.app.update()
        self.assertEqual(pane.capture_direction.get(),"RX")
        self.assertEqual(len(picker.table.get_children()),3)
        picker.table.selection_set(("2","0"));picker.add_selected()
        from probe.scenario import compile_steps
        self.assertEqual([s.payload for s in compile_steps(pane.effective_rows())],[b"FIRST\0",b"LAST\xff"])
        self.assertEqual([s.delay_ms for s in compile_steps(pane.effective_rows())],[100,100])
        picker=pane.use_capture();pane.capture_direction.set("TX");picker.refresh();picker.add_selected()
        self.assertEqual(compile_steps(pane.effective_rows())[-1].payload,b"COMMAND")
        self.assertEqual(self.app.vars["side"].get(),"Device / upstream")
        self.assertIn("COM34",pane.destination_text())
        self.app.vars["side"].set("App / downstream")
        self.assertIn("application / downstream",pane.destination_text())
        self.assertNotIn("COM34",pane.destination_text())

    def test_sequence_shared_interval_is_visible_exported_and_used_on_wire(self):
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.macros=[dict(name="First",text="00 02 FF",send_mode="Hex",delay_ms=900),
                         dict(name="Second",text="00 7A",send_mode="Hex",delay_ms=900)]
        pane.adopt_timing();pane.refresh()
        pane.interval.set("100");self.app.update()
        self.assertEqual([pane.table.set(str(i),"delay") for i in range(2)],["100","100"])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"sequence.json"
            with patch("probe.sequence_ui.filedialog.asksaveasfilename",return_value=str(path)):pane.save_file()
            self.assertEqual([r["delay_ms"] for r in json.loads(path.read_text())["steps"]],[100,100])
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        self.app.vars["interval"].set("not the sequence interval")
        pane.run();self.spin(lambda:"Sequence complete" in self.app.sequence_info.get())
        sent=[e for e in self.app.events.values() if e["direction"]=="TX"]
        self.assertEqual([e["data"] for e in sent],[b"\x00\x02\xff",b"\x00z"])
        self.assertGreaterEqual(sent[1]["time"]-sent[0]["time"],.085)
        self.assertLess(sent[1]["time"]-sent[0]["time"],.8)

    def test_sequence_import_keeps_advanced_timing_and_legacy_defaults(self):
        self.app.macro_dialog();pane=self.app.sequence_panel
        pane.repeat_mode.set(pane.REPEATS[1])
        self.app.vars["sequence_cycles"].set("1")
        self.assertEqual(pane.repeat_mode.get(),pane.REPEATS[1])
        self.app.vars["sequence_cycles"].set("0")
        with self.assertRaises(ValueError):pane.run_cycles()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"advanced.json"
            original=[dict(name="A",text="41",send_mode="Hex",delay_ms=7,repeat=3,expect="42",timeout_ms=90),
                      dict(name="B",text="43",send_mode="Hex",delay_ms=80)]
            path.write_text(json.dumps(dict(format="probe-sequence",version=1,cycles=0,steps=original)))
            with patch("probe.sequence_ui.filedialog.askopenfilename",return_value=str(path)):pane.load_file()
            self.assertTrue(pane.individual.get())
            self.assertEqual(pane.repeat_mode.get(),pane.REPEATS[2])
            self.assertEqual(pane.effective_rows(),original)
            pane.individual.set(False);pane.interval.set("100")
            self.assertEqual([(r["delay_ms"],r.get("expect")) for r in pane.effective_rows()],[(100,"42"),(100,None)])
            pane.individual.set(True)
            self.assertEqual(pane.effective_rows(),original)
            path.write_text(json.dumps([dict(name="Legacy",text="00 FF",send_mode="Hex")]))
            with patch("probe.sequence_ui.filedialog.askopenfilename",return_value=str(path)),patch("probe.sequence_ui.messagebox.askyesno",return_value=True):pane.load_file()
            self.assertFalse(pane.individual.get())
            self.assertEqual(pane.interval.get(),"100")
            self.assertEqual(pane.effective_rows()[0]["delay_ms"],100)

    def test_sequence_editor_cancel_validation_and_exact_transformed_bytes(self):
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.vars["send_mode"].set("Hex");self.app.vars["prefix"].set("02")
        self.app.vars["ending"].set("CRLF")
        self.app.payload.delete("1.0","end");self.app.payload.insert("1.0","00 FF")
        pane.add_composer();pane.open_editor(0);self.app.update()
        self.assertEqual(pane.payload.get("1.0","end-1c"),"02 00 FF 0D 0A")
        pane.payload.delete("1.0","end");pane.payload.insert("1.0","GG")
        pane.action(pane.save_editor)
        self.assertIn("Hex",pane.editor_feedback.get())
        self.assertTrue(pane.editor.winfo_exists())
        pane.editor.destroy()
        from probe.scenario import compile_steps
        self.assertEqual(compile_steps(pane.effective_rows())[0].payload,b"\x02\x00\xff\r\n")
        pane.open_editor(0);pane.fields["name"].set("Renamed")
        pane.save_editor()
        self.assertEqual(compile_steps(pane.effective_rows())[0].payload,b"\x02\x00\xff\r\n")
        self.assertEqual(self.app.macros[0]["name"],"Renamed")

    def test_sequence_continuous_stop_and_editing_lock(self):
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.macros=[dict(name="A",text="41",send_mode="Hex")];pane.refresh()
        pane.repeat_mode.set(pane.REPEATS[2])
        self.app.choose_mode("USB / Serial");self.app.vars["serial_port"].set("loop://")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        pane.run();self.spin(lambda:self.app.engine.tx>=2)
        self.assertTrue(pane.run_button.instate(["disabled"]))
        with self.assertRaisesRegex(ValueError,"Stop"):pane.add_composer()
        pane.stop();self.spin(lambda:self.app.engine.scenario_task is None)
        count=self.app.engine.tx
        self.spin(lambda:not pane.run_button.instate(["disabled"]))
        self.assertEqual(self.app.engine.tx,count)
        self.assertTrue(pane.stop_button.instate(["disabled"]))

    def test_sequence_reply_mode_export_import_and_timing_switch(self):
        from probe.scenario import compile_steps
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.macros=[dict(name="A",text="41",send_mode="Hex",delay_ms=7),
                         dict(name="B",text="42",send_mode="Hex",delay_ms=80,expect="06")]
        pane.adopt_timing();pane.refresh()
        pane.advance.set("After a reply");pane.reply_timeout.set("500");self.app.update()
        self.assertTrue(pane.timeout_entry.winfo_ismapped())
        self.assertFalse(pane.interval_entry.winfo_ismapped())
        self.assertFalse(pane.individual_check.winfo_ismapped())
        pane.interval.set("unused")
        self.assertEqual([(s.delay_ms,s.wait_for_reply,s.timeout_ms) for s in compile_steps(pane.effective_rows())],[(0,True,500)]*2)
        self.assertEqual(pane.table.set("0","options"),"Any reply")
        self.assertEqual(pane.table.set("1","options"),"Match reply")
        pane.open_editor(0);pane.fields["name"].set("Renamed");pane.save_editor()
        pane.table.selection_set("1");pane.duplicate()
        pane.advance.set("After interval")
        self.assertEqual([(s.delay_ms,s.wait_for_reply) for s in compile_steps(pane.effective_rows())],[(7,False),(80,False),(80,False)])
        pane.advance.set("After a reply");pane.reply_timeout.set("0")
        with self.assertRaisesRegex(ValueError,"Reply timeout"):pane.effective_rows()
        pane.reply_timeout.set("500")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"reply-sequence.json"
            expected=pane.effective_rows()
            with patch("probe.sequence_ui.filedialog.asksaveasfilename",return_value=str(path)):pane.save_file()
            self.assertEqual(json.loads(path.read_text())["version"],2)
            self.app.macros=[]
            pane.advance.set("After interval")
            with patch("probe.sequence_ui.filedialog.askopenfilename",return_value=str(path)):pane.load_file()
            self.assertEqual(pane.advance.get(),"After a reply")
            self.assertEqual(pane.reply_timeout.get(),"500")
            self.assertEqual(pane.effective_rows(),expected)

    def test_sequence_reply_mode_on_wire_and_stop_while_waiting(self):
        import socket
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.macros=[dict(name="First",text="A"),dict(name="Second",text="B")]
        pane.advance.set("After a reply");pane.reply_timeout.set("2000");pane.refresh()
        self.app.choose_mode("TCP Server");self.app.vars["listen_port"].set("0")
        self.app.toggle();self.spin(lambda:self.app.engine.ready)
        with socket.create_connection(self.app.engine.server.sockets[0].getsockname()[:2],timeout=2) as device:
            self.spin(lambda:len(self.app.engine.clients)==1)
            pane.run();self.assertEqual(device.recv(1),b"A")
            self.spin(lambda:"waiting for reply" in pane.status.get())
            self.assertFalse(pane.stop_button.instate(["disabled"]))
            self.assertTrue(pane.advance_combo.instate(["disabled"]))
            self.assertEqual(self.app.engine.tx,1)
            device.sendall(b"ACK");self.assertEqual(device.recv(1),b"B")
            device.sendall(b"DONE");self.spin(lambda:"Sequence complete" in pane.status.get())
            self.assertIn("2 replies checked",pane.status.get())
            pane.reply_timeout.set("3600000")
            pane.run();self.assertEqual(device.recv(1),b"A")
            self.spin(lambda:"waiting for reply" in pane.status.get())
            pane.stop_button.focus_force();self.app.update()
            self.assertEqual(self.app.focus_get(),pane.stop_button)
            pane.stop_button.invoke()
            self.spin(lambda:"Sequence stopped" in pane.status.get())
            self.assertEqual(self.app.engine.tx,3)

    def test_buttons_have_readable_disabled_text_and_solid_focus(self):
        self.app.macro_dialog();pane=self.app.sequence_panel
        def luminance(color):
            channels=[v/65535 for v in self.app.winfo_rgb(color)]
            channels=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
            return sum(v*w for v,w in zip(channels,(.2126,.7152,.0722)))
        from probe.app import DARK, LIGHT
        for theme,colors in (("Probe Dark",DARK),("Light",LIGHT)):
            self.app.vars["theme"].set(theme);self.app.colors=dict(colors);self.app._style()
            for style in ("TButton","Accent.TButton"):
                self.assertNotIn("Button.focus",str(self.app.style.layout(style)))
                for state in (("disabled",),("disabled","active"),("!disabled","focus")):
                    light,dark=sorted((luminance(self.app.style.lookup(style,"foreground",state)),
                                       luminance(self.app.style.lookup(style,"background",state))),reverse=True)
                    self.assertGreaterEqual((light+.05)/(dark+.05),4.5)
        # The dotted element is removed, but keyboard focus is still supported.
        self.assertTrue(pane.stop_button.cget("takefocus"))

    def test_protocol_inspector_exact_field_highlight_and_custom_profile(self):
        wire=b'000001{"data":{"sessionId":"123","code":"000"}}'
        self.app.add_event(dict(kind="data",direction="RX",peer="COM34",time=time.time(),data=wire))
        self.app.table.selection_set(self.app.order[-1]);window=self.app.analyze();pane=window.protocol
        self.app.update();self.assertFalse(hasattr(self.app,"analyze_button"))
        index=next(i for i,field in enumerate(pane.fields) if field.selector=="/data/sessionId")
        pane.view.selection_set(str(index));pane.highlight();pane.copy_path()
        self.assertEqual(self.app.clipboard_get(),"/data/sessionId")
        self.assertTrue(pane.hex.tag_ranges("field"))
        self.assertEqual(wire[pane.fields[index].offset:pane.fields[index].offset+pane.fields[index].size],b'"123"')
        editor=pane.edit_fields();editor.edit();editor.field_variables["name"].set("Size")
        editor.field_variables["kind"].set("Length ASCII");editor.field_variables["length"].set("6")
        editor.save_field();editor.save();self.app.update()
        self.assertEqual(pane.fields[0].name,"Size")
        self.assertEqual(pane.fields[0].status,"Mismatch")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"protocol.json"
            with patch("probe.analysis_ui.filedialog.asksaveasfilename",return_value=str(path)):pane.save_profile()
            pane.set_fields([])
            with patch("probe.analysis_ui.filedialog.askopenfilename",return_value=str(path)):pane.load_profile()
            self.assertEqual(pane.fields[0].name,"Size")
        self.assertIsNone(self.app.engine)

    def test_capture_diff_ignore_json_field_and_report_preserves_bytes(self):
        a=b'{"sid":"1","amount":100}';b=b'{"sid":"longer","amount":100}'
        for index,data in enumerate((a,b)):self.app.add_event(dict(kind="data",direction="RX",peer="COM34",time=time.time()+index,data=data))
        self.app.table.selection_set(self.app.order[-1]);window=self.app.analyze("Compare");pane=window.comparison
        self.app.update();self.assertEqual((pane.a,pane.b),(a,b))
        dialog=pane.ignore_dialog();self.app.update()
        iid=next(i for i in pane.ignore_view.get_children() if pane.ignore_view.set(i,"path")=="/sid")
        pane.ignore_view.selection_set(iid);pane.apply_ignores();self.app.update()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual([item.kind for item in pane.differences if item.kind!="equal"],["ignored"])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"diff.json"
            with patch("probe.analysis_ui.filedialog.asksaveasfilename",return_value=str(path)):pane.save()
            report=json.loads(path.read_text());self.assertEqual(bytes.fromhex(report["a_hex"]),a);self.assertEqual(bytes.fromhex(report["b_hex"]),b)
        self.assertIsNone(self.app.engine)

    def test_analysis_picker_combines_chunks_without_replacing_history(self):
        from probe.analysis_ui import TrafficPicker
        original=[("RX",b'{"sid":'),("TX",b"A"),("RX",b'"123"}')]
        for n,(direction,data) in enumerate(original):self.app.add_event(dict(kind="data",direction=direction,peer="COM34",time=time.time()+n,data=data))
        result=[];picker=TrafficPicker(self.app,lambda data,label:result.append(data));self.app.update()
        picker.view.selection_set(picker.view.get_children());picker.choose()
        self.assertEqual(result,[b'{"sid":"123"}'])
        self.assertEqual([self.app.events[i]["data"] for i in self.app.order],[data for _,data in original])

    def test_sequence_response_rules_picker_cancel_ids_and_v3_export(self):
        from probe.scenario import compile_steps
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.macros=[dict(name="Ready",text="PING",delay_ms=0),dict(name="Use session",text="${sid}",delay_ms=0)]
        pane.individual.set(True);pane.refresh();pane.open_editor(0)
        rules=pane.response_rules();self.app.update()
        rules.reply_chosen(b'{"data":{"sessionId":"123"}}',"Example reply")
        iid=next(i for i in rules.reply_field_view.get_children() if rules.reply_field_view.set(i,"field")=="/data/sessionId")
        rules.reply_field_view.selection_set(iid);rules.choose_reply_field();rules.name.set("sid");rules.put()
        rules.check.set(True);rules.condition_variable.set("sid");rules.expected.set("123");rules.toggle_condition()
        rules.geometry("820x680");rules.tabs.select(1);self.app.update()
        for _,_,line in rules.routes.values():
            self.assertTrue(line.winfo_ismapped())
            self.assertLess(line.winfo_rooty()+line.winfo_height(),rules.winfo_rooty()+rules.winfo_height()-70)
        rules.routes["on_true"][0].set("Go to message");rules.routes["on_true"][1].set(next(label for label in rules.destinations if label.startswith("2 ·")))
        rules.save();pane.save_editor()
        compiled=compile_steps(pane.effective_rows())
        self.assertEqual(compiled[0].flow.extract[0].selector,"/data/sessionId")
        target=compiled[1].step_id;self.assertEqual(compiled[0].flow.on_true.target,target)
        pane.table.selection_set("1");pane.move(-1)
        self.assertEqual(compile_steps(pane.effective_rows())[1].flow.on_true.target,target)
        pane.open_editor(1);pane.response_rules().clear();pane.editor.destroy()
        self.assertTrue(self.app.macros[1].get("flow"))
        variables=pane.variables_dialog();variables.name.set("amount");variables.kind.set("JSON");variables.value.set("100");variables.put();variables.save()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"flow.json"
            with patch("probe.sequence_ui.filedialog.asksaveasfilename",return_value=str(path)):pane.save_file()
            document=json.loads(path.read_text());self.assertEqual(document["version"],3);self.assertIn("amount",document["variables"])
            self.app.macros=[]
            with patch("probe.sequence_ui.filedialog.askopenfilename",return_value=str(path)):pane.load_file()
            self.assertEqual(compile_steps(pane.effective_rows())[1].flow.on_true.target,target)

    def test_sequence_variables_and_branch_run_over_real_tcp(self):
        import socket
        from test_sequence_flow import rows
        self.app.macro_dialog();pane=self.app.sequence_panel
        self.app.macros=rows();pane.individual.set(True);pane.refresh()
        self.app.choose_mode("TCP Server");self.app.vars["listen_port"].set("0");self.app.toggle();self.spin(lambda:self.app.engine.ready)
        with socket.create_connection(self.app.engine.server.sockets[0].getsockname()[:2],timeout=3) as device:
            self.spin(lambda:len(self.app.engine.clients)==1);pane.run()
            self.assertEqual(device.recv(4),b"PING");device.sendall(b'{"data":{"sessionId":"123"}}')
            wire=bytearray()
            while len(wire)<6:wire.extend(device.recv(6-len(wire)))
            size=int(wire);body=bytearray()
            while len(body)<size:body.extend(device.recv(size-len(body)))
            self.assertEqual(json.loads(body)["sessionId"],"123")
            self.spin(lambda:"Sequence complete" in pane.status.get())
            self.assertEqual(self.app.sequence_values["sid"],"123")

    def test_lab_com_pair_configuration_and_application_endpoint(self):
        import socket
        now = time.time()
        self.app.add_event(dict(kind="data", time=now, direction="TX", peer="device", data=b"QUERY"))
        self.app.add_event(dict(kind="data", time=now+.001, direction="RX", peer="device", data=b"ANSWER"))
        # Present the Windows panel even on a POSIX test host; I/O uses real pySerial.
        with patch("probe.testlab_ui.simulator_transports", return_value=("TCP socket", "Virtual COM pair")), \
             patch("probe.app.simulator_transports", return_value=("TCP socket", "Virtual COM pair")), \
             socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(); listener.settimeout(3)
            win = self.app.test_lab(); win.geometry("980x680")
            pane = self.app.simulator_panel
            pane.use_history()
            self.app.vars["simulator_transport"].set("Virtual COM pair")
            self.app.vars["simulator_port"].set("socket://127.0.0.1:%d" % listener.getsockname()[1])
            self.app.vars["simulator_peer_port"].set("COM21")
            pane.start(); self.spin(lambda: self.app.engine.ready)
            self.spin(lambda: "App-side port: COM21" in self.app.status.cget("text"))
            with listener.accept()[0] as connection:
                connection.settimeout(3)
                connection.sendall(b"QUERY")
                actual = bytearray()
                while len(actual) < 6:
                    chunk = connection.recv(6-len(actual))
                    self.assertTrue(chunk); actual.extend(chunk)
                self.assertEqual(bytes(actual), b"ANSWER")
                self.spin(lambda: "COM21" in self.app.simulator_info.get() and "requests matched" in self.app.simulator_info.get())
                self.assertEqual(self.app.clipboard_get(), "COM21")
                pane.stop(); self.spin(lambda: not self.app.active)

if __name__=="__main__":unittest.main()
