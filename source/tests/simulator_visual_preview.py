"""Native simulator editor previews; Pillow is a developer-only dependency."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from probe.app import Probe
from probe.simulation import model_from_dict
from probe.ui.testlab import read_json
from PIL import ImageGrab

with tempfile.TemporaryDirectory() as directory,patch('probe.app.data_directory',return_value=Path(directory)):
    app=Probe();app.geometry('1200x800+0+0');app.update()
    lab=app.test_lab();lab.geometry('1040x720+0+0');app.update()
    pane=app.simulator_panel
    pane.install(model_from_dict(read_json(Path(__file__).resolve().parents[1]/'examples/simulator-json-faults.json')))
    def capture(win,name):
        win.update();win.lift();win.update()
        ImageGrab.grab(bbox=(win.winfo_rootx(),win.winfo_rooty(),win.winfo_rootx()+win.winfo_width(),win.winfo_rooty()+win.winfo_height())).save('probe-preview-simulator-'+name+'.png')
    capture(lab,'overview');pane.table.selection_set('0')
    rule=pane.edit_rule();rule.geometry('+20+20');capture(rule,'request')
    rule.notebook.select(1);capture(rule,'fault');rule.destroy()
    framing=pane.edit_framing();framing.geometry('+20+20');capture(framing,'framing');framing.destroy()
    app.close()
