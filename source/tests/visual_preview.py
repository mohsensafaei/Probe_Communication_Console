"""Optional developer preview: Pillow is used only for capturing screenshots."""
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.app import Probe, LIGHT
from PIL import ImageGrab

with tempfile.TemporaryDirectory() as directory, patch('probe.app.data_directory',return_value=Path(directory)):
    app=Probe(demo=True)
    app.geometry('1200x800+0+0')
    for _ in range(30):app.update();time.sleep(.02)
    # Real Tk rendering, not a UI mockup.
    ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save('probe-preview-dark.png')
    app.close()
    import probe.app as module
    with patch.object(module,'DARK',LIGHT):
        app=Probe(demo=True);app.vars['theme'].set('Light');app._style();app.geometry('1200x800+0+0')
        for _ in range(30):app.update();time.sleep(.02)
        ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save('probe-preview-light.png')
        app.close()
