from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.app import Probe
from PIL import ImageGrab

with tempfile.TemporaryDirectory() as directory,patch('probe.app.data_directory',return_value=Path(directory)):
    window=Probe();window.geometry('1200x850+0+0')
    first=window.current_probe;second=window.new_probe()
    for probe,name,mode in ((first,'App → Service','TCP Proxy'),(second,'Service → POS','Serial Proxy')):
        window.names[probe]=name;probe.choose_mode(mode);window.update_probe_title(probe)
        probe.add_event(dict(kind='data',time=time.time(),direction='TX',peer=name,data=b'{"service":"03","amount":"100000"}'))
        probe.add_event(dict(kind='data',time=time.time(),direction='RX',peer=name,data=b'{"responseCode":"000"}'))
    window.update();window.current_probe.set_status('MULTI-PROBE PREVIEW · synthetic sample traffic; no connections opened.')
    window.update_idletasks()
    ImageGrab.grab(bbox=(window.winfo_rootx(),window.winfo_rooty(),window.winfo_rootx()+window.winfo_width(),window.winfo_rooty()+window.winfo_height())).save('probe-preview-multi-probe.png')
    tabs=window.probe_tabs
    for x in range(8,tabs.winfo_width(),2):
        if tabs.identify(x,16)=='Probe.close':tabs.event_generate('<Motion>',x=x,y=16,warp=True);break
    for _ in range(5):window.update();time.sleep(.03)
    ImageGrab.grab(bbox=(window.winfo_rootx(),window.winfo_rooty(),window.winfo_rootx()+window.winfo_width(),window.winfo_rooty()+window.winfo_height())).save('probe-preview-tab-close.png')
    first.add_event(dict(kind='data',time=time.time(),direction='TX',peer='App',data=b'{"sessionId":"123","amount":100000}'))
    second.add_event(dict(kind='data',time=time.time(),direction='TX',peer='POS',data=b'{"sessionId":"123","amount":10000}'))
    trace=window.trace_path(first);trace.field.set('sessionId');trace.match();trace.geometry('1100x650+20+20')
    if not trace.winfo_viewable():trace.wait_visibility()
    trace.lift();trace.focus_force()
    for _ in range(10):window.update();time.sleep(.03)
    ImageGrab.grab(bbox=(trace.winfo_rootx(),trace.winfo_rooty(),trace.winfo_rootx()+trace.winfo_width(),trace.winfo_rooty()+trace.winfo_height())).save('probe-preview-trace-path.png')
    window.close()
