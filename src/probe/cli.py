import json
import sys
from pathlib import Path

from . import __version__


def main():
    import argparse
    parser=argparse.ArgumentParser(description="Probe communications workbench")
    parser.add_argument("--demo",action="store_true",help="Show synthetic traffic without opening a connection")
    parser.add_argument("--version",action="version",version=__version__)
    parser.add_argument("--self-test",action="store_true",help="Test bundled serial, PTY, network and terminal support without a display")
    parser.add_argument("--smoke-test",action="store_true",help="Open the GUI briefly and verify all transport panels")
    parser.add_argument("--diagnostic-report",type=Path,help="Write self-test/smoke-test results as JSON (also works in windowed Windows builds)")
    parser.add_argument("--hid-helper",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--hid-port",type=int,default=0,help=argparse.SUPPRESS)
    parser.add_argument("--hid-token",default="",help=argparse.SUPPRESS)
    parser.add_argument("--hid-action",choices=("list","capture","check"),default="capture",help=argparse.SUPPRESS)
    parser.add_argument("--hid-source",default="",help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.hid_helper:
        from .hid.helper import helper_main
        helper_main(args.hid_port,args.hid_token,args.hid_action,args.hid_source)
        return
    def report(success, error=""):
        if args.diagnostic_report:
            args.diagnostic_report.write_text(json.dumps(dict(success=success, version=__version__,
                platform=sys.platform, check="self-test" if args.self_test else "smoke-test", error=error)), encoding="utf-8")
    if args.self_test:
        from .diagnostics import self_test
        try:
            self_test()
        except Exception as exc:
            report(False, str(exc))
            print(f"Self-test failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
        report(True)
        return
    if args.diagnostic_report and not args.smoke_test:
        parser.error("--diagnostic-report requires --self-test or --smoke-test")
    if sys.platform=="win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:pass
    from .app import Probe
    try:
        app=Probe(demo=args.demo)
    except Exception as exc:
        if not args.smoke_test: raise
        report(False, str(exc))
        raise SystemExit(1)
    if args.smoke_test:
        app.current_probe.save_settings=lambda: None
        from .ui.diagnostics import smoke_test
        app.after(300,lambda:smoke_test(app,report))
        app.report_callback_exception=lambda *error: sys.exit(1)
    app.mainloop()
