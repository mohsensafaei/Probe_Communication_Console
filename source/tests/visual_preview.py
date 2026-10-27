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
    app.vars['search_mode'].set('Hex bytes');app.vars['search'].set('02');app.refresh(force=True);app.update()
    ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save('probe-preview-search.png')
    app.clear_search()
    app.notebook.select(app.plot)
    for i in range(50):app.plot.feed(dict(direction="RX",peer="Sensor",data=f"{20+(i%10)*.3},{22+(i%7)*.2}\n".encode()))
    app.geometry('1060x700+0+0');app.update();app.plot.render(force=True);app.update()
    ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save('probe-preview-plot.png')
    app.geometry('1200x800+0+0');app.update()
    dialog=app.plot.configure_custom();app.update()
    ImageGrab.grab(bbox=(dialog.winfo_rootx(),dialog.winfo_rooty(),dialog.winfo_rootx()+dialog.winfo_width(),dialog.winfo_rooty()+dialog.winfo_height())).save('probe-preview-custom.png')
    dialog.destroy()
    app.table.selection_set(app.order[-1]);analysis=app.analyze('Compare');app.update()
    ImageGrab.grab(bbox=(analysis.winfo_rootx(),analysis.winfo_rooty(),analysis.winfo_rootx()+analysis.winfo_width(),analysis.winfo_rooty()+analysis.winfo_height())).save('probe-preview-analysis.png')
    app.close()
    import probe.app as module
    with patch.object(module,'DARK',LIGHT):
        app=Probe(demo=True);app.vars['theme'].set('Light');app._style();app.geometry('1200x800+0+0')
        for _ in range(30):app.update();time.sleep(.02)
        ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save('probe-preview-light.png')
        app.close()
