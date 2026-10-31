"""Developer preview of real Tk HID views with synthetic reports; never captures USB."""
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from probe.app import Probe
from probe.hid_reports import HidTracker
from probe.hid_ui import devices_received

MOUSE=bytes.fromhex('05010902A1010901A1000509190129031500250175019503810295017505810105010930093109381581257F750895038106C0C0')

def snapshot(window,name):
    for _ in range(12):window.update();time.sleep(.02)
    x,y=window.winfo_rootx(),window.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height())).save(name)

with tempfile.TemporaryDirectory() as directory,patch('probe.app.data_directory',return_value=Path(directory)):
    app=Probe();app.geometry('1200x800+0+0');app.choose_mode('HID Monitor')
    devices_received(app,dict(devices=[dict(name='Demo USB mouse (synthetic)',source='1:2')]))
    tracker=HidTracker({0:[0x81]},{0:MOUSE.hex()})
    for index,data in enumerate((b'\x00\x05\x02\x00',b'\x01\x00\x00\x00',b'\x00\x00\x00\xff',b'\x05\xfe\x03\x00')):
        event=tracker.consume(dict(id=index,time=time.time(),bus=1,device=2,status=0,stage='complete',
            transfer='interrupt',endpoint=0x81,payload=data,setup='',length=len(data)))
        app.emit(event)
    app.set_status('DEMO PREVIEW · synthetic HID reports; no USB capture or permission request.')
    snapshot(app,'probe-preview-hid.png')
    app.table.selection_set(app.order[-1]);analysis=app.analyze();analysis.geometry('1000x760+0+0')
    snapshot(analysis,'probe-preview-hid-analysis.png')
    app.close()
