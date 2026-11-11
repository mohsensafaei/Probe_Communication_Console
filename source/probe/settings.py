import json
import os
import sys
from pathlib import Path

DEFAULTS = dict(mode="TCP Client", host="127.0.0.1", port="9000", bind="127.0.0.1",
                listen_port="9001", serial_port="", baud="115200", bits="8", parity="N",
                stopbits="1", flow="None", app_port="Auto PTY" if os.name != "nt" else "COM20",
                app_peer_port="COM21", simulator_port="COM20", simulator_peer_port="COM21",
                send_mode="Text", encoding="utf-8", ending="None", checksum="None",
                prefix="", suffix="", interval="1000", framing="Chunks", delimiter="0A",
                frame_size="16", gap="50", view="Text + Hex", search="", search_mode="Text", direction="All", plugins="[]",
                target="All clients", side="Device / upstream", profile="Default", auto="Off",
                theme="Probe Dark", sequence_cycles="1", sequence_interval="100", sequence_timing="auto",
                sequence_advance="After interval", sequence_reply_timeout="2000", sequence_variables="{}",
                hid_device="", usb_serial_device="", tcp_device="", tcp_port="9000", plot_mode="Auto", plot_config="{}", protocol_fields="[]", simulator_transport="TCP socket",
                simulator_matching="Conversation order", simulator_timing="1")

BOOL_DEFAULTS = {'dtr': False, 'rts': False, 'autoscroll': True, 'repeat': False, 'reconnect': False, 'sequence_loop': False, 'simulator_repeat': True}


def data_directory():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    preferred = base / "probe-data"
    try:
        preferred.mkdir(exist_ok=True)
        check = preferred / ".writable"; check.write_text(""); check.unlink()
        return preferred
    except OSError:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()/".local"/"share")) / "Probe"
        base.mkdir(parents=True, exist_ok=True); return base


def read_settings(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_settings(path, last, profiles, macros):
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(version=1, profiles=profiles, macros=macros, last=last), indent=2), encoding="utf-8")
    temporary.replace(path)
