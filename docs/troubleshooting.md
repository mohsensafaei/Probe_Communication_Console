# Troubleshooting

| Symptom | Check |
| --- | --- |
| No Traffic rows | Connected? Correct probe/direction? Reset search and unpause. Check endpoint/client selection. |
| Data split across rows | Choose framing; TCP/serial reads are not message boundaries. |
| Serial port missing | Refresh after plugging in. Confirm the OS exposes a serial interface, not only HID/MTP. |
| Port already open | Close the application that owns the physical port; use a configured proxy for shared inspection. |
| TCP connection refused | Confirm server listen address/port and firewall; target is not the proxy's own port. |
| Live plot empty | Use complete LF numeric lines or configure Custom with the correct boundary/field/peer. |
| Terminal unreadable | Check encoding, baud/line settings and whether the payload is actually binary. |
| Replay/import rejected | Export with Hex enabled; decoded text alone is not a byte capture. |
| Plugin failed | Read the reported error, disconnect and Apply to restart the worker. Verify the plugin in source Python. |
| HID has raw bytes only | Descriptor unavailable/ambiguous; supply the actual descriptor in Analyze → HID Report. |
| Settings not next to executable | Portable directory is unwritable; check the per-user fallback or PROBE_DATA_DIR. |

## Linux serial permissions

Run `ls -l /dev/ttyUSB0` (substitute your port). Its owning group controls access.
On Debian/Ubuntu this is commonly `dialout`. An administrator can grant membership:

```sh
sudo usermod -aG dialout "$USER"
```

Log out of the desktop session and back in. A running process does not acquire new
group membership automatically. Prefer `/dev/serial/by-id/` for stable device names.
Do not run the entire application as root to work around normal port permissions.

## Runtime diagnostics

From source:

```sh
python -m probe --version
python -m probe --self-test --diagnostic-report report.json
python -m probe --smoke-test --diagnostic-report gui-report.json
```

Use `./Probe` or `.\Probe.exe` instead for portable builds. The GUI smoke test
requires a desktop display; on headless Linux run under `xvfb-run -a`. Reports work
with windowed Windows executables too. Self-test uses local sockets/loopback/PTYs
where supported, not external hardware or privileged HID capture.

For a source launch failure, run `python -m tkinter` and check that the same Python
has the installed dependencies. For a portable Linux library error, use a build
compatible with your distribution or rebuild on that distribution. Portable does
not mean independent of every host OS library.

## Report a reproducible bug

Include Probe version, OS/Python or archive name, mode/settings, steps, expected
behavior, actual result and a small sanitized capture. Include diagnostic reports
when relevant. Distinguish real hardware from loopback/PTY tests. Remove secrets,
payment details and identifying device data before posting. Use the repository's
[bug template](https://github.com/mohsensafaei/Probe_Communication_Console/issues/new?template=bug_report.yml).
