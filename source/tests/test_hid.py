"""Capture-format fixtures, HID fields and the on-demand privilege boundary."""
import io
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from probe.engine import Engine
from probe.hid_capture import (USBMON_HEADER, USBPCAP_HEADER, parse_usbmon, parse_usbpcap,
    pcap_packets, parse_extcap_devices, validate_source, linux_devices, bundled_installer)
from probe.hid_helper import HelperClient, send_message, receive_message, helper_command, launch_helper
from probe.hid_monitor import run_monitor
from probe.hid_reports import ReportDescriptor, HidTracker, interfaces_from_config
from probe.traffic_search import TrafficSearch

MOUSE=bytes.fromhex('05010902A1010901A1000509190129031500250175019503810295017505810105010930093109381581257F750895038106C0C0')
KEYBOARD=bytes.fromhex('05010906A101050719E029E71500250175019508810295017508810195067508150025650507190029658100C0')
CONFIG=bytes.fromhex('09022200010100A0320904000001030102000921110100012234000705810308000A')

def packet(ident=1,stage='complete',endpoint=0x81,data=b'\x01\xfe\x03\x00'):
    return dict(id=ident,stage=stage,endpoint=endpoint,payload=data,status=0,transfer='interrupt',
                bus=1,device=2,time=123.5,setup='',length=len(data))

class DescriptorTests(unittest.TestCase):
    def test_mouse_signed_fields_and_padding(self):
        fields,note=ReportDescriptor(MOUSE).decode(b'\x05\xfe\x03\xff')
        self.assertEqual([(f['field'],f['value']) for f in fields],
            [('Button 1','1'),('Button 2','0'),('Button 3','1'),('X','-2'),('Y','3'),('Wheel','-1')])
        self.assertEqual(fields[3]['bit'],8);self.assertTrue(fields[3]['relative'])

    def test_keyboard_array_and_modifiers(self):
        fields,_=ReportDescriptor(KEYBOARD).decode(bytes([2,0,4,5,0,0,0,0]))
        self.assertEqual(fields[1]['value'],'1');self.assertEqual(fields[8]['value'],'Key A (4)')
        self.assertEqual(fields[9]['value'],'Key B (5)')

    def test_numbered_input_output_feature_and_truncation(self):
        desc=ReportDescriptor(bytes.fromhex('0600FF0901A1018503150026FF007508950281029102B102C0'))
        for kind in ('Input','Output','Feature'):
            fields,_=desc.decode(b'\x03\x1A\x2B',kind)
            self.assertEqual([f['value'] for f in fields],['26','43']);self.assertEqual(fields[0]['bit'],8)
        self.assertEqual(desc.decode(b'\x04\x01','Input')[0],[])
        self.assertIn('Truncated',desc.decode(b'\x03\x01','Input')[1])

    def test_malformed_descriptors_are_bounded(self):
        for data in (b'\x76',b'\xfe\x08\x01\x00',bytes.fromhex('8500'),
                     bytes.fromhex('750897FFFFFFFF8102'),bytes.fromhex('B4')):
            with self.assertRaises(ValueError):ReportDescriptor(data)
        with self.assertRaises(ValueError):ReportDescriptor(bytes(16385))

class CaptureFormatTests(unittest.TestCase):
    def test_usbpcap_and_usbmon_have_identical_semantics(self):
        data=b'\x01\xfe\x03\x00'
        win=parse_usbpcap(USBPCAP_HEADER.pack(27,42,0,9,1,1,2,0x81,1,len(data))+data,123.5)
        header=USBMON_HEADER.pack(42,ord('C'),1,0x81,2,1,45,0,123,500000,0,len(data),len(data),bytes(8),0,0,0,0)
        self.assertEqual(win,parse_usbmon(header,data))

    def test_fragmented_pcap_and_invalid_headers(self):
        data=USBPCAP_HEADER.pack(27,7,0,9,1,1,2,0x81,1,4)+b'ABCD'
        stream=struct.pack('<IHHIIII',0xA1B2C3D4,2,4,0,0,65535,249)+struct.pack('<IIII',123,500000,len(data),len(data))+data
        class Fragmented(io.BytesIO):
            def read(self,size=-1):return super().read(min(size,3))
        self.assertEqual(list(pcap_packets(Fragmented(stream)))[0]['payload'],b'ABCD')
        with self.assertRaises(OSError):list(pcap_packets(io.BytesIO(stream[:-1])))
        with self.assertRaises(ValueError):parse_usbpcap(bytes(27),0)

    def test_extcap_tree_and_source_allowlist(self):
        text='value {arg=99}{value=2}{display=[2] Composite USB}{enabled=true}\nvalue {arg=99}{value=2_1}{display=HID keyboard}{enabled=false}{parent=2}'
        devices=parse_extcap_devices(r'\\.\USBPcap1',text)
        self.assertEqual(devices[0]['source'],r'\\.\USBPcap1:2');self.assertIn('keyboard',devices[0]['name'])
        validate_source(devices[0]['source'],True);validate_source('1:127',False)
        for source in ('0:1','1:0','1:128','1:2;rm','/etc/shadow',r'\\.\PhysicalDrive0:1'):
            with self.assertRaises(ValueError):validate_source(source,False)

    @unittest.skipUnless(os.name=="posix","sysfs interface names contain colon characters")
    def test_linux_discovery_filters_hid_without_privilege_operations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);device=root/'1-2';device.mkdir();interface=root/'1-2:1.0';interface.mkdir()
            for name,value in dict(busnum='1',devnum='2',product='Lab keypad',idVendor='1234',idProduct='5678').items():
                (device/name).write_text(value)
            (interface/'bInterfaceClass').write_text('03');(interface/'bInterfaceNumber').write_text('00')
            self.assertEqual(linux_devices(root)[0]['source'],'1:2')
            (interface/'bInterfaceClass').write_text('08');self.assertEqual(linux_devices(root),[])

    def test_bundled_original_installer_integrity(self):
        self.assertEqual(bundled_installer().read_bytes()[:2],b'MZ')

class ReconstructionTests(unittest.TestCase):
    def tracker(self):return HidTracker({0:[0x81,1]}, {0:MOUSE.hex()})

    def test_input_completion_once_and_output_uses_submission(self):
        tracker=self.tracker();self.assertIsNone(tracker.consume(packet(stage='submit',data=b'')))
        event=tracker.consume(packet());self.assertEqual(event['direction'],'RX')
        self.assertEqual(event['data'],b'\x01\xfe\x03\x00');self.assertEqual(event['hid']['fields'][3]['value'],'-2')
        self.assertIsNone(tracker.consume(packet(2,'submit',1,b'OUT')))
        event=tracker.consume(packet(2,'complete',1,b''));self.assertEqual(event['direction'],'TX')
        self.assertEqual(event['data'],b'OUT');self.assertFalse(event['hid']['truncated'])
        p=packet(3);p['status']=-1;self.assertIsNone(tracker.consume(p))

    def test_control_feature_get_set_and_descriptor(self):
        tracker=self.tracker()
        def control(ident,stage,setup='',data=b''):
            p=packet(ident,stage,0,data);p.update(transfer='control',setup=setup);return p
        setup=struct.pack('<BBHHH',0xA1,1,0x0300,0,4).hex()
        self.assertIsNone(tracker.consume(control(3,'submit',setup)))
        event=tracker.consume(control(3,'complete',data=b'ABCD'))
        self.assertEqual(event['hid']['report_type'],'Feature');self.assertEqual(event['direction'],'RX')
        setup=struct.pack('<BBHHH',0x21,9,0x0200,0,3).hex()
        self.assertIsNone(tracker.consume(control(4,'submit',setup,b'XYZ')))
        event=tracker.consume(control(4,'complete'));self.assertEqual(event['data'],b'XYZ')
        self.assertEqual(event['direction'],'TX')
        setup=struct.pack('<BBHHH',0x81,6,0x2200,0,len(KEYBOARD)).hex()
        tracker.consume(control(5,'submit',setup));tracker.consume(control(5,'complete',data=KEYBOARD))
        self.assertEqual(tracker.descriptors[0].data,KEYBOARD)
        self.assertEqual(interfaces_from_config(CONFIG),{0:{0x81}})

    def test_other_interfaces_excluded_and_missing_descriptor_explicit(self):
        tracker=HidTracker({0:[0x81]})
        self.assertIsNone(tracker.consume(packet(endpoint=0x82)))
        event=tracker.consume(packet());self.assertEqual(event['hid']['fields'],[])
        self.assertIn('unavailable',event['hid']['note'])

    def test_monitor_retains_bytes_and_disables_send(self):
        events=[];engine=Engine(events.append);engine.cfg=dict(mode='HID Monitor',hid_source=r'\\.\USBPcap1:2' if os.name=='nt' else '1:2')
        messages=[dict(kind='metadata',interfaces={0:[0x81]},descriptors={0:MOUSE.hex()}),
                  dict(kind='ready'),dict(kind='packet',packet={**packet(),'payload':'01FE0300'})]
        with patch('probe.hid_monitor.HelperClient') as helper:
            helper.return_value.messages.return_value=iter(messages);run_monitor(engine)
        event=next(e for e in events if e['kind']=='data');self.assertEqual(event['data'],b'\x01\xfe\x03\x00')
        self.assertTrue(TrafficSearch('X=-2').matches(event))
        self.assertTrue(TrafficSearch('FE 03',mode='Hex bytes').matches(event))
        with self.assertRaises(RuntimeError):engine.send(b'A')
        with self.assertRaises(ValueError):engine.start_scenario(())

class HelperBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows source launcher')
    def test_windows_launcher_understands_platform_marker_pins(self):
        from windows_bootstrap import requirements
        pins=requirements(False)
        self.assertIn('hidapi==0.15.0',pins)
        self.assertTrue(all(len(pin.split('=='))==2 for pin in pins))

    def test_framing_and_invalid_length(self):
        left,right=socket.socketpair()
        with left,right:
            send_message(left,dict(kind='ping'));self.assertEqual(receive_message(right),dict(kind='ping'))
            left.sendall(struct.pack('!I',0))
            with self.assertRaises(ValueError):receive_message(right)

    def test_real_unelevated_helper_without_capture(self):
        stop=threading.Event();messages=list(HelperClient().messages('check','',stop,elevate=False))
        self.assertTrue(any(m.get('kind')=='checked' for m in messages));self.assertTrue(stop.is_set())

    def test_launch_does_not_use_a_shell(self):
        command=helper_command(1234,'a'*64,'capture','1:2');self.assertIn('--hid-helper',command)
        with patch('probe.hid_helper.subprocess.Popen') as process:
            launch_helper(['probe','--version'],False)
            self.assertNotIn('shell',process.call_args.kwargs)

    def test_jsonl_import_retains_and_revalidates_hid_fields(self):
        import json
        from probe.capture import load_capture
        event=HidTracker({0:[0x81]},{0:MOUSE.hex()}).consume(packet())
        row={key:value for key,value in event.items() if key!='data'}
        row['hex']=event['data'].hex()
        # Imported UI field strings are recomputed from the actual descriptor.
        row['hid']['fields']=[dict(field='Injected',value='wrong')]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'hid.jsonl';path.write_text(json.dumps(row)+'\n')
            restored=load_capture(path)[0]
            self.assertEqual(restored['data'],event['data'])
            self.assertEqual(restored['hid']['fields'][3]['value'],'-2')
            row['hid']['endpoint']=999;path.write_text(json.dumps(row)+'\n')
            with self.assertRaises(ValueError):load_capture(path)

    def test_monitor_does_not_emit_reports_after_stop(self):
        events=[];engine=Engine(events.append)
        engine.cfg=dict(mode='HID Monitor',hid_source=r'\\.\USBPcap1:2' if os.name=='nt' else '1:2')
        def messages(*args,**kwargs):
            yield dict(kind='ready')
            engine.stopping.set()
            yield dict(kind='packet',packet={**packet(),'payload':'01FE0300'})
        with patch('probe.hid_monitor.HelperClient') as helper:
            helper.return_value.messages.side_effect=messages;run_monitor(engine)
        self.assertFalse(any(event['kind']=='data' for event in events))
