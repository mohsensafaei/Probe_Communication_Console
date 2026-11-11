import os
import socket
import struct
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from probe.diagnostics import session, wait_for
from probe.hid_helper import helper_main, receive_message, send_message
from probe.usb_serial import SerialTarget, SerialTransfers, linux_target, serial_endpoints, validate_port


def config(*parts):
    data = b''.join(parts)
    return struct.pack('<BBHBBBBB',9,2,len(data)+9,1,1,0,0x80,50)+data


def interface(number, cls, subclass=0, alternate=0, count=2):
    return bytes((9,4,number,alternate,count,cls,subclass,0,0))


def ep(address, size=64):
    return struct.pack('<BBBBHB',7,5,address,2,size,0)


def cdc(control, data, first_ep):
    return (interface(control,2,2,count=0),bytes((5,0x24,6,control,data)),interface(data,10),ep(first_ep),ep(first_ep|128))


def packet(endpoint, stage, payload=b'', *, identity=5, length=None, status=0):
    return dict(transfer='bulk',endpoint=endpoint,id=identity,stage=stage,payload=payload,
                length=len(payload) if length is None else length,status=status,time=1700000000.25)


class SerialDecoderTests(unittest.TestCase):
    def test_cdc_composite_filters_to_selected_function(self):
        descriptor = config(*cdc(0,1,2),*cdc(2,3,4),interface(4,255),ep(6),ep(0x86))
        self.assertEqual(serial_endpoints(descriptor,1,2,'CDC ACM'),{4:64,0x84:64})
        self.assertEqual(serial_endpoints(descriptor,1,1,'CDC ACM'),{2:64,0x82:64})
        with self.assertRaisesRegex(ValueError,'unambiguous'):serial_endpoints(descriptor,1,None,'CDC ACM')
        with self.assertRaisesRegex(ValueError,'Truncated'):serial_endpoints(descriptor[:-1],1,2,'CDC ACM')

    def test_only_successful_bulk_transfers_and_ftdi_status_bytes(self):
        descriptor = config(interface(0,255),ep(2,8),ep(0x81,8))
        tracker = SerialTransfers('FTDI',serial_endpoints(descriptor,1,0,'FTDI'),True)
        self.assertIsNone(tracker.consume(packet(0x81,'submit')))
        self.assertIsNone(tracker.consume(packet(0x82,'complete',b'unrelated')))
        self.assertEqual(tracker.consume(packet(0x81,'complete',b'\x01\x60abcdef\x01\x60XY')),('RX',b'abcdefXY'))
        self.assertIsNone(tracker.consume(packet(2,'submit',b'query')))
        self.assertEqual(tracker.consume(packet(2,'complete')),('TX',b'query'))
        self.assertIsNone(tracker.consume(packet(2,'complete')))
        with self.assertRaisesRegex(OSError,'truncated'):tracker.consume(packet(0x81,'complete',b'xx',length=8))

    def test_linux_uses_actual_write_completion_length(self):
        tracker = SerialTransfers('CDC ACM',{2:64,0x82:64},False)
        tracker.consume(packet(2,'submit',b'hello'))
        self.assertEqual(tracker.consume(packet(2,'complete',length=3)),('TX',b'hel'))
        tracker.consume(packet(2,'submit',b'lost'))
        with self.assertRaisesRegex(OSError,'write failed'):tracker.consume(packet(2,'complete',status=-32))

    def test_rejects_non_usb_port_paths_and_injection(self):
        for bad,windows in [('COM34 --hid-action list',True),('COM0',True),('/dev/ttyS0',False),('/dev/../ttyUSB0',False)]:
            with self.assertRaises(ValueError):validate_port(bad,windows)

    @unittest.skipUnless(os.name=='posix','Uses sysfs-style symlinks')
    def test_linux_target_is_bound_to_selected_tty(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);device=root/'1-1';control=device/'1-1:1.0';data=device/'1-1:1.1'
            control.mkdir(parents=True);data.mkdir();(root/'cdc_acm').mkdir();(root/'ttyACM0').mkdir()
            (control/'driver').symlink_to(root/'cdc_acm');(root/'ttyACM0'/'device').symlink_to(control)
            for path,value in ((device/'idVendor','1234'),(device/'idProduct','abcd'),(device/'busnum','1'),
                               (device/'devnum','4'),(device/'bConfigurationValue','1'),(control/'bInterfaceNumber','00'),
                               (data/'bInterfaceNumber','01'),(control/'bAlternateSetting','0'),(data/'bAlternateSetting','0')):
                path.write_text(value)
            (device/'descriptors').write_bytes(config(*cdc(0,1,2)))
            target=linux_target('/dev/ttyACM0',root)
            self.assertEqual((target.source,target.endpoints),('1:4',{2:64,0x82:64}))
            self.assertTrue(target.attached());(device/'devnum').write_text('5');self.assertFalse(target.attached())


class WindowsBindingTests(unittest.TestCase):
    def test_selects_exact_driver_key_and_root_hub_with_identical_devices(self):
        from probe.usb_serial_windows import windows_target
        root=r'USB\ROOT_HUB30\A&B'
        correct=r'\\.\USBPcap2';other=r'\\.\USBPcap1'
        descriptor=config(*cdc(0,1,2),*cdc(2,3,4))
        device=bytearray(18);struct.pack_into('<HH',device,8,0x1234,0xabcd);device[17]=1

        class Api:
            key='exact-device';address=17
            def chain(self,node):
                return [(1,r'USB\VID_1234&PID_ABCD&MI_02\SER'),(2,r'USB\VID_1234&PID_ABCD\SER'),(3,root)]
            def property(self,node,key):return 'usbser' if (node,key)==(1,5) else 'exact-device' if (node,key)==(2,10) else ''
            def hub(self,node):return 'hub'
            def handle(self,path,*args):return nullcontext(path)
            def driver_key(self,handle,index):return self.key if index==3 else 'identical-other-device'
            def ioctl(self,handle,code,request=b'',size=4096):
                if code==0x220408:return b'\0'*6+b'\x04'
                if code==0x220448:
                    if request != b'\x03\0\0\0':raise AssertionError('wrong physical port')
                    return struct.pack('<I',3)+device+b'\x01\x02\0'+struct.pack('<HII',self.address,2,1)
                if code==0x220410:return request+descriptor[:size-12]
                if code==0x22200c:
                    identity=root if handle==correct else r'USB\ROOT_HUB30\OTHER'
                    return ('\\??\\'+identity.replace('\\','#')+'#{guid}\0').encode('utf-16-le')
                raise AssertionError(code)
        api=Api()
        with patch('probe.usb_serial_windows.com_nodes',return_value=[1]),patch('probe.usb_serial_windows.UsbApi',return_value=api), \
             patch('probe.usb_serial_windows.windows_sources',return_value=[other,correct]):
            target=windows_target('COM34')
            self.assertEqual(target.source,correct+':17');self.assertEqual(target.endpoints,{4:64,0x84:64})
            self.assertTrue(target.attached());api.address=18;self.assertFalse(target.attached())

    @unittest.skipUnless(os.name=='nt','Requires Windows SetupAPI')
    def test_native_windows_metadata_apis_load_without_opening_a_serial_port(self):
        from probe.usb_serial_windows import UsbApi, com_nodes
        self.assertIsNotNone(UsbApi().hub_guid)
        self.assertEqual(list(com_nodes('COM65535')),[])


class MonitorTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Uses the Linux helper path')
    def test_helper_revalidates_device_before_forwarding_after_disconnect(self):
        attached=threading.Event();attached.set()
        target=SerialTarget('1:4','CDC ACM',{2:64,130:64},attached.is_set)
        def capture(source,send,stop,endpoints):
            send(dict(kind='ready'));stop.wait(3)
        with socket.socket() as listener, patch('probe.usb_serial.linux_target',return_value=target), \
             patch('probe.hid_helper.capture_linux',side_effect=capture) as backend:
            listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(3)
            token='f'*64
            worker=threading.Thread(target=helper_main,args=(listener.getsockname()[1],token,'serial','/dev/ttyACM0'),daemon=True)
            worker.start()
            sock,_=listener.accept()
            with sock:
                sock.settimeout(3)
                self.assertEqual(receive_message(sock),{'token':token});send_message(sock,{'token':token})
                self.assertEqual(receive_message(sock)['kind'],'serial_metadata')
                self.assertEqual(receive_message(sock)['kind'],'ready')
                self.assertEqual((backend.call_args.args[0],backend.call_args.args[3]),('1:4',target.endpoints))
                attached.clear();send_message(sock,{'kind':'ping'})
                self.assertIn('disconnected',receive_message(sock)['message'])
            worker.join(3);self.assertFalse(worker.is_alive())

    def test_engine_captures_without_send_and_keeps_usb_time(self):
        port='COM34' if os.name=='nt' else '/dev/ttyACM0'
        raw=packet(0x82,'complete',b'reply');raw['payload']=raw['payload'].hex()
        messages=[dict(kind='serial_metadata',profile='CDC ACM',endpoints={'2':64,'130':64}),
                  dict(kind='ready'),dict(kind='packet',packet=raw)]
        def stream(action,source,stop,**kwargs):
            self.assertEqual((action,source),('serial',port))
            yield from messages
            stop.wait(3)
        with patch('probe.usb_serial_monitor.HelperClient') as helper,patch('probe.usb_serial_monitor.linux_target') as target:
            target.return_value.source='1:4';helper.return_value.messages.side_effect=stream
            with session('USB Serial Monitor',usb_serial_port=port) as (engine,events,_):
                wait_for(lambda:engine.rx==5,events)
                with self.assertRaisesRegex(RuntimeError,'capture-only'):engine.send(b'forbidden')
            row=next(e for e in events if e['kind']=='data')
            self.assertEqual((row['time'],row['peer'],row['data']),(1700000000.25,port,b'reply'))
            self.assertNotIn('monotonic_ns',row)
