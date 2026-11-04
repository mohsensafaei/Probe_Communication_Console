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
    window.close()
