import math

from ..codec import Framer
from ..serial_endpoints import VirtualPair, simulator_transports
from . import MODES


def validate(cfg, simulator_model=None, hid_devices=None):
    mode=cfg["mode"]
    if mode not in MODES: raise ValueError("Choose a supported transport mode.")
    if mode in ("TCP Client","TCP Proxy","UDP"):
        if not cfg["host"].strip(): raise ValueError("Enter a remote host.")
        p=int(cfg["port"])
        if not 1<=p<=65535: raise ValueError("Remote port must be 1–65535.")
    if mode in ("TCP Server","TCP Proxy","UDP","Serial ↔ TCP") or (mode == "Device Simulator" and cfg["simulator_transport"] == "TCP socket"):
        p=int(cfg["listen_port"])
        if not 0<=p<=65535: raise ValueError("Listen port must be 0–65535.")
    if mode == "Device Simulator":
        from ..simulation import RequestMatcher
        if not simulator_model: raise ValueError("Open Test lab and load a capture or build a device model first.")
        RequestMatcher(simulator_model, cfg["simulator_matching"] == "Conversation order", cfg["simulator_repeat"])
        scale=float(cfg["simulator_timing"])
        if not math.isfinite(scale) or not 0 <= scale <= 10: raise ValueError("Reply timing multiplier must be 0–10.")
        if cfg["simulator_transport"] not in simulator_transports():
            raise ValueError("Choose a supported simulator transport for this operating system.")
        if cfg["simulator_transport"] == "Virtual COM pair":
            VirtualPair(cfg["simulator_port"], cfg["simulator_peer_port"]).validate()
    if mode == "Serial Proxy" and cfg["app_port"] != "Auto PTY":
        VirtualPair(cfg["app_port"], cfg["app_peer_port"]).validate(cfg["serial_port"])
    if "Serial" in mode:
        if not cfg["serial_port"]: raise ValueError("Choose or enter a physical serial port.")
        if int(cfg["baud"])<1: raise ValueError("Baud must be positive.")
    if mode == "HID Monitor":
        source=(hid_devices or {}).get(cfg["hid_device"])
        if not source:raise ValueError("Refresh devices, then choose a USB device before starting HID capture.")
        cfg["hid_source"]=source
        from ..hid_capture import validate_source
        validate_source(source)
    display_framer(cfg)


def display_framer(cfg):
    from ..codec import parse_hex
    return Framer(cfg["framing"],parse_hex(cfg["delimiter"]),
                  int(cfg["frame_size"]),max(1,int(cfg["gap"]))/1000)
