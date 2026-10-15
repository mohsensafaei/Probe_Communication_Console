import contextlib
import json
import os
import queue
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from probe.codec import encode, parse_hex, crc16_modbus, checksum, Framer, hexdump
from probe.engine import Engine

def wait_for(predicate, timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.01)
    raise AssertionError("Timed out waiting for a transport event")

def receive(sock,n):
    out=bytearray()
    while len(out)<n:
        data=sock.recv(n-len(out))
        if not data:break
        out.extend(data)
    return bytes(out)

class CodecTests(unittest.TestCase):
    def test_binary_payload(self):
        self.assertEqual(encode("02 A4 00 FF 03","Hex"),bytes([2,164,0,255,3]))
        self.assertEqual(parse_hex("0x02,0xA4:00-FF_03"),bytes([2,164,0,255,3]))

    def test_unicode_and_escapes(self):
        self.assertEqual(encode("سلام\\r\\n\\xFF","Escaped"),"سلام".encode()+b"\r\n\xff")
        self.assertEqual(encode("0 127,255","Decimal"),b"\x00\x7f\xff")

    def test_invalid_data(self):
        for value in ("A","GG","0x010"):
            with self.assertRaises(ValueError):parse_hex(value)
        with self.assertRaises(ValueError):encode("256","Decimal")
        with self.assertRaises(ValueError):encode("\\xG1","Escaped")
        with self.assertRaises(ValueError):encode("\\q","Escaped")

    def test_crc_reference_vectors(self):
        self.assertEqual(crc16_modbus(b"123456789"),0x4B37)
        self.assertEqual(checksum(b"123456789","CRC16 CCITT"),bytes.fromhex("29 B1"))
        self.assertEqual(checksum(b"123456789","CRC32"),bytes.fromhex("26 39 F4 CB"))

    def test_payload_layout(self):
        self.assertEqual(encode("01 02","Hex",ending="CRLF",check="SUM8",prefix="AA",suffix="03"),bytes.fromhex("AA 01 02 AD 03 0D 0A"))

    def test_split_and_coalesced_frames(self):
        f=Framer("Delimiter",b"\r\n")
        self.assertEqual(f.feed(b"a\r",0),[])
        self.assertEqual(f.feed(b"\nb\r\nc",1),[b"a\r\n",b"b\r\n"])
        self.assertEqual(f.flush(),[b"c"])
        f=Framer("Fixed length",size=3)
        self.assertEqual(f.feed(b"01234567",0),[b"012",b"345"])
        self.assertEqual(f.flush(),[b"67"])

    def test_idle_and_bounds(self):
        f=Framer("Idle gap",idle=.05)
        self.assertEqual(f.feed(b"a",1),[])
        self.assertEqual(f.tick(1.01),[])
        self.assertEqual(f.tick(1.1),[b"a"])
        f=Framer("Delimiter",b"\n")
        self.assertEqual(len(f.feed(b"x"*65536,0)[0]),65536)

    def test_dump(self):
        self.assertIn("00000000",hexdump(b"abc\x00\xff"))
        self.assertIn("61 62 63 00 FF",hexdump(b"abc\x00\xff"))

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.engines=[];self.sockets=[]
        self.payload=bytes(range(256))*64+b"\x00\xff\x02\x03"

    def tearDown(self):
        for e in self.engines:e.stop()
        for s in self.sockets:
            with contextlib.suppress(Exception):s.close()
        for e in self.engines:
            e.join();self.assertFalse(e.thread.is_alive(),"Transport thread leaked")

    def engine(self,mode,**kw):
        events=[];e=Engine(events.append);self.engines.append(e)
        cfg=dict(mode=mode,host="127.0.0.1",port=9000,bind="127.0.0.1",listen_port=0,
                 baud=115200,bits=8,parity="N",stopbits=1,flow="None",dtr=False,rts=False)
        cfg.update(kw);e.start(cfg)
        ready=wait_for(lambda:next((x for x in events if x["kind"] in ("error","state") and (x.get("state")=="Connected" or x["kind"]=="error")),None))
        self.assertEqual(ready["kind"],"state",ready)
        return e,events,ready

    def sock(self,addr):
        s=socket.create_connection(addr,timeout=4);self.sockets.append(s);return s

    @staticmethod
    def stream(events,direction):
        return b"".join(x["data"] for x in events if x["kind"]=="data" and x["direction"]==direction)

    def test_tcp_client_server_exact_duplex(self):
        server,se,ready=self.engine("TCP Server")
        host,port=ready["address"][:2]
        client,ce,_=self.engine("TCP Client",host=host,port=port)
        client.send(self.payload)
        wait_for(lambda:len(self.stream(se,"RX"))==len(self.payload))
        self.assertEqual(self.stream(se,"RX"),self.payload)
        server.send(self.payload[::-1])
        wait_for(lambda:len(self.stream(ce,"RX"))==len(self.payload))
        self.assertEqual(self.stream(ce,"RX"),self.payload[::-1])

    def test_server_select_and_broadcast(self):
        e,events,ready=self.engine("TCP Server")
        a=self.sock(ready["address"][:2]);b=self.sock(ready["address"][:2])
        wait_for(lambda:len(e.clients)==2)
        e.send(b"ALL");self.assertEqual(receive(a,3),b"ALL");self.assertEqual(receive(b,3),b"ALL")
        target=list(e.clients)[0];e.send(b"ONE",target)
        self.assertEqual(receive(a,3),b"ONE")
        b.settimeout(.1)
        with self.assertRaises(socket.timeout):b.recv(1)

    def test_proxy_binary_and_multiple_clients(self):
        upstream,ue,ready=self.engine("TCP Server");upstream.echo=True
        proxy,pe,pr=self.engine("TCP Proxy",port=ready["address"][1])
        clients=[self.sock(pr["address"][:2]) for _ in range(2)]
        for s in clients:s.sendall(self.payload);self.assertEqual(receive(s,len(self.payload)),self.payload)
        wait_for(lambda:len(self.stream(pe,"RX"))==2*len(self.payload))
        self.assertEqual(proxy.tx,2*len(self.payload));self.assertEqual(proxy.rx,2*len(self.payload))

    def test_proxy_half_close(self):
        listener=socket.socket();listener.bind(("127.0.0.1",0));listener.listen();self.sockets.append(listener)
        errors=[]
        def upstream():
            try:
                conn,_=listener.accept();conn.settimeout(4)
                with conn:
                    data=bytearray()
                    while True:
                        chunk=conn.recv(1024)
                        if not chunk:break
                        data.extend(chunk)
                    conn.sendall(b"REPLY:"+data)
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=upstream);thread.start()
        e,events,ready=self.engine("TCP Proxy",port=listener.getsockname()[1])
        s=self.sock(ready["address"][:2]);s.sendall(b"request\x00\xff");s.shutdown(socket.SHUT_WR)
        self.assertEqual(receive(s,15),b"REPLY:request\x00\xff")
        thread.join(4);self.assertEqual(errors,[])

    def test_proxy_injection_both_directions(self):
        upstream,ue,ur=self.engine("TCP Server")
        proxy,pe,pr=self.engine("TCP Proxy",port=ur["address"][1])
        s=self.sock(pr["address"][:2]);wait_for(lambda:len(proxy.clients)==1)
        proxy.send(b"UP");wait_for(lambda:self.stream(ue,"RX")==b"UP")
        proxy.send(b"DOWN",side="App / downstream");self.assertEqual(receive(s,4),b"DOWN")

    def test_udp_exact_and_reply_to_sender(self):
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(("127.0.0.1",0));s.settimeout(4);self.sockets.append(s)
        e,events,ready=self.engine("UDP",port=s.getsockname()[1]);e.echo=True
        data=bytes(range(256));s.sendto(data,ready["address"])
        self.assertEqual(s.recvfrom(4096)[0],data)
        e.echo=False;e.send(b"OUT");self.assertEqual(s.recvfrom(4096)[0],b"OUT")

    def test_recording_lossless(self):
        e,events,ready=self.engine("TCP Server")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"session.jsonl";raw=Path(directory)/"rx.bin"
            e.record(path);e.record(raw,raw=True)
            s=self.sock(ready["address"][:2]);s.sendall(self.payload)
            wait_for(lambda:e.rx==len(self.payload));e.record();e.record(raw=True)
            rows=[json.loads(x) for x in path.read_text().splitlines()]
            captured=b"".join(bytes.fromhex(x["hex"]) for x in rows if x["kind"]=="data")
            self.assertEqual(captured,self.payload);self.assertEqual(raw.read_bytes(),self.payload)

    def test_disconnect_cleans_listener(self):
        e,events,ready=self.engine("TCP Server")
        addr=ready["address"][:2];e.stop();e.join()
        with self.assertRaises(OSError):socket.create_connection(addr,timeout=.2)

    def test_connection_failure(self):
        s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close()
        events=[];e=Engine(events.append);self.engines.append(e);e.start(dict(mode="TCP Client",host="127.0.0.1",port=port))
        wait_for(lambda:any(x["kind"]=="error" for x in events));e.join()
        self.assertFalse(e.ready)

    def test_serial_loop(self):
        e,events,_=self.engine("USB / Serial",serial_port="loop://")
        # pySerial's simulated queue is 4096 bytes; use a smaller vector.
        data=bytes(range(256));e.send(data)
        wait_for(lambda:len(self.stream(events,"RX"))==len(data))
        self.assertEqual(self.stream(events,"RX"),data)

    @unittest.skipIf(os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
                     "Requires unprivileged POSIX device permissions")
    def test_serial_permission_error_explains_device_group(self):
        master, slave = os.openpty()
        name = os.ttyname(slave)
        permissions = os.stat(name).st_mode & 0o777
        events = []
        engine = Engine(events.append)
        self.engines.append(engine)
        try:
            os.chmod(name, 0)
            engine.start(dict(mode="USB / Serial", serial_port=name))
            error = wait_for(lambda: next((e for e in events if e["kind"] == "error"), None))
            self.assertIn("Permission denied", error["message"])
            self.assertIn("sudo usermod -aG", error["message"])
            self.assertIn("log out and back in", error["message"])
            engine.join()
            self.assertFalse(engine.ready)
            self.assertEqual(engine.serials, [])
        finally:
            os.chmod(name, permissions)
            os.close(master)
            os.close(slave)

    @unittest.skipIf(os.name == "nt", "PTY test requires POSIX")
    def test_serial_unplug_disconnects_cleanly(self):
        import tty
        master, slave = os.openpty()
        tty.setraw(slave)
        try:
            e, events, _ = self.engine("USB / Serial", serial_port=os.ttyname(slave))
            os.close(master)
            master = None
            wait_for(lambda: any(x["kind"] == "error" for x in events))
            e.join()
            self.assertFalse(e.ready)
            self.assertFalse(e.serials[0].is_open)
            self.assertTrue(any(x.get("state") == "Disconnected" for x in events))
        finally:
            if master is not None: os.close(master)
            os.close(slave)

    @unittest.skipIf(os.name=="nt","PTY test requires POSIX")
    def test_serial_proxy_pty(self):
        import serial,tty
        master,slave=os.openpty();tty.setraw(slave);name=os.ttyname(slave)
        try:
            e,events,ready=self.engine("Serial Proxy",serial_port=name,app_port="Auto PTY")
            app=serial.Serial(ready["app_path"],115200,timeout=3)
            try:
                tx=b"app\x00\xff\x02\x03";rx=b"device\x00\xff\r\n"
                app.write(tx)
                wait_for(lambda:len(self.stream(events,"TX"))==len(tx))
                self.assertEqual(os.read(master,1024),tx)
                os.write(master,rx);self.assertEqual(app.read(len(rx)),rx)
                wait_for(lambda:len(self.stream(events,"RX"))==len(rx))
            finally:app.close();e.stop();e.join()
        finally:os.close(master);os.close(slave)

    @unittest.skipIf(os.name=="nt","PTY test requires POSIX")
    def test_serial_tcp_bridge(self):
        import tty
        master,slave=os.openpty();tty.setraw(slave)
        try:
            e,events,ready=self.engine("Serial ↔ TCP",serial_port=os.ttyname(slave))
            s=self.sock(ready["address"][:2]);s.sendall(b"TCP\x00")
            wait_for(lambda:e.tx==4);self.assertEqual(os.read(master,100),b"TCP\x00")
            os.write(master,b"SERIAL\xff");self.assertEqual(receive(s,7),b"SERIAL\xff")
            e.stop();e.join()
        finally:os.close(master);os.close(slave)

if __name__=="__main__":unittest.main()
