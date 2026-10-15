import json
from pathlib import Path
import tempfile
import unittest
from probe.terminal import TerminalModel, key_bytes
from probe.capture import load_capture, replay_plan
from probe.codec import encode

class TerminalTests(unittest.TestCase):
    def test_split_unicode_and_split_escape(self):
        m=TerminalModel(30,4)
        data="سلام".encode()
        m.feed(data[:3]);m.feed(data[3:]+b"\x1b[3");m.feed(b"1mRED\x1b[0m")
        self.assertTrue(m.screen.display[0].startswith("سلامRED"))
        self.assertEqual(m.screen.buffer[0][4].fg,"red")

    def test_cursor_clear_and_carriage_return(self):
        m=TerminalModel(20,4);m.feed(b"long line\rnew\x1b[K")
        self.assertEqual(m.screen.display[0].strip(),"new")
        m.feed(b"\x1b[3;5Hxy")
        self.assertEqual(m.screen.display[2][4:6],"xy")
        m.feed(b"\x1b[2J\x1b[H")
        self.assertTrue(all(not line.strip() for line in m.screen.display))

    def test_alternate_screen_restores_content_and_cursor(self):
        m=TerminalModel(20,4);m.feed(b"primary");cursor=(m.screen.cursor.x,m.screen.cursor.y)
        m.feed(b"\x1b[?1049halternate")
        self.assertEqual(m.screen.display[0].strip(),"alternate")
        m.feed(b"\x1b[?1049l")
        self.assertEqual(m.screen.display[0].strip(),"primary")
        self.assertEqual((m.screen.cursor.x,m.screen.cursor.y),cursor)

    def test_attributes_truecolor_and_dsr(self):
        m=TerminalModel(20,4);m.feed(b"\x1b[1;4;38;2;17;34;51mA")
        char=m.screen.buffer[0][0]
        self.assertTrue(char.bold);self.assertTrue(char.underscore);self.assertEqual(char.fg,"112233")
        self.assertEqual(m.feed(b"\x1b[6n"),[b"\x1b[1;2R"])

    def test_history_is_bounded(self):
        m=TerminalModel(20,4)
        for i in range(1300):m.feed(f"{i}\r\n".encode())
        self.assertLessEqual(len(m.screen.history.top),1000)
        self.assertIn("1299","".join(m.screen.display))

    def test_keyboard_uses_exact_controls(self):
        self.assertEqual(key_bytes("Return",enter="CRLF"),b"\r\n")
        self.assertEqual(key_bytes("c",control=True),b"\x03")
        self.assertEqual(key_bytes("Up"),b"\x1b[A")
        self.assertEqual(key_bytes("Up",application_cursor=True),b"\x1bOA")
        self.assertEqual(key_bytes("BackSpace",backspace="BS"),b"\x08")
        self.assertEqual(key_bytes("BackSpace"),b"\x7f")
        self.assertEqual(key_bytes("F12"),b"\x1b[24~")

    def test_oversized_control_strings_are_bounded(self):
        m=TerminalModel(20,4)
        m.feed(b"before\x1b]2;"+b"x"*100000)
        self.assertLessEqual(len(m.filter.buffer),4096)
        m.feed(b"\x07after")
        self.assertEqual(m.screen.display[0].strip(),"beforeafter")
        m.feed(b"\x1b["+b"9"*10000+b"mOK")
        self.assertIn("OK",m.screen.display[0])

    def test_escape_filter_preserves_split_charset_and_osc(self):
        m=TerminalModel(20,4)
        m.feed(b"\x1b(");m.feed(b"BA\x1b]2;title\x1b");m.feed(b"\\B")
        self.assertEqual(m.screen.display[0].strip(),"AB")

class CaptureTests(unittest.TestCase):
    def test_legacy_byte_tokens_are_exact(self):
        self.assertEqual(encode("<STX>Hello#000$FF<CR><LF><ETX>","Hercules"),b"\x02Hello\x00\xff\r\n\x03")
        self.assertEqual(encode("## $$ <<","Hercules"),b"# $ <")
        with self.assertRaises(ValueError):encode("#256","Hercules")
        with self.assertRaises(ValueError):encode("$GG","Hercules")

    def test_lrc_checksum(self):
        self.assertEqual(encode("01 02 03","Hex",check="LRC8"),b"\x01\x02\x03\xfa")
    def test_jsonl_with_metadata_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"capture.jsonl"
            path.write_text(json.dumps(dict(kind="info",time=1,message="open"))+"\n"+json.dumps(dict(kind="data",time=2,direction="TX",peer="local",hex="0002A4FF"))+"\n")
            rows=load_capture(path)
            self.assertEqual(rows[0]["data"],bytes.fromhex("00 02 A4 FF"))
            self.assertEqual(rows[0]["time"],2)

    def test_csv_import(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"capture.csv"
            path.write_text('timestamp,direction,peer,hex\n2026-10-14T00:00:00,RX,test,00 FF\n')
            self.assertEqual(load_capture(path)[0]["data"],b"\x00\xff")

    def test_replay_keeps_relative_timing_and_direction(self):
        rows=[dict(time=5,direction="TX",data=b"a"),dict(time=6,direction="RX",data=b"x"),dict(time=9,direction="TX",data=b"b")]
        self.assertEqual(replay_plan(rows,2),[(0,b"a"),(2,b"b")])
        self.assertEqual(replay_plan(rows,1,"RX"),[(0,b"x")])

    def test_malformed_and_bounded_import(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"capture.jsonl"
            path.write_text(json.dumps(dict(time=0,direction="TX",hex="GG")))
            with self.assertRaises(ValueError):load_capture(path)
            path.write_text(json.dumps(dict(time=0,direction="TX",hex="000102")))
            with self.assertRaises(ValueError):load_capture(path,max_bytes=2)
            with self.assertRaises(ValueError):replay_plan([],0)

if __name__=="__main__":unittest.main()
