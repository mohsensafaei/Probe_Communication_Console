"""Load bundled OFL fonts privately; never install fonts on the user's system."""
import ctypes
import ctypes.util
import os
from pathlib import Path
import sys

_handles = []


def load_fonts():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    files = sorted((root / "assets" / "fonts").glob("*.ttf"))
    try:
        if os.name == "nt":
            gdi = ctypes.WinDLL("gdi32", use_last_error=True)
            gdi.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
            gdi.AddFontResourceExW.restype = ctypes.c_int
            for path in files:
                gdi.AddFontResourceExW(str(path), 0x10, None)  # FR_PRIVATE
            _handles.append(gdi)
        else:
            fc = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
            fc.FcConfigGetCurrent.restype = ctypes.c_void_p
            fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            fc.FcConfigAppFontAddFile.restype = ctypes.c_int
            fc.FcConfigBuildFonts.argtypes = [ctypes.c_void_p]
            config = fc.FcConfigGetCurrent()
            for path in files:
                fc.FcConfigAppFontAddFile(config, os.fsencode(path))
            fc.FcConfigBuildFonts(config)
            _handles.append(fc)
    except (OSError, AttributeError):
        pass  # Tk's built-in fonts are the offline fallback.


def font_roles(root):
    from tkinter import font
    families = set(font.families(root))
    body = "Rajdhani" if "Rajdhani" in families else font.nametofont("TkDefaultFont", root=root).actual("family")
    heading = body  # Unified Probe typography; no imitation of a vendor wordmark.
    mono = "Share Tech Mono" if "Share Tech Mono" in families else font.nametofont("TkFixedFont", root=root).actual("family")
    return body, heading, mono
