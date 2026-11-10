# Probe

[![CI](https://github.com/mohsensafaei/Probe_Communication_Console/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mohsensafaei/Probe_Communication_Console/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A portable communications workbench for Windows and Linux. Connect to hardware,
inspect bytes, reproduce conversations and follow a message through several points
in your application. Written in Python with a native Tk interface.

## Download

Get the native ZIP for your system from [Releases](https://github.com/mohsensafaei/Probe_Communication_Console/releases/latest):

| System | Portable archive | Start |
| --- | --- | --- |
| Windows x64 | `Probe-<version>-windows-x86_64.zip` | Extract, then open `Probe.exe` |
| Linux x64 | `Probe-<version>-linux-x86_64.zip` | Extract, then run `./start-probe.sh` |

Portable builds include Python and runtime dependencies. Normal operation does not
request administrator access. HID capture may require a driver or elevated helper;
see [HID monitoring](docs/hid.md). Downloads include SHA-256 checksums. If no release
asset is available yet, use [source installation](docs/installation.md) or a
[CI build artifact](https://github.com/mohsensafaei/Probe_Communication_Console/actions/workflows/ci.yml).

## What you can do

| Task | Tools |
| --- | --- |
| Communicate | TCP client/server/proxy, UDP, USB serial, serial proxy and Serial ↔ TCP |
| Inspect | Traffic search in text/hex, decoded text, hex + ASCII, byte inspector and protocol fields |
| Compare | Capture Diff, multi-select export and Trace path across up to eight probes |
| Reproduce | Raw recording, capture import/replay, timed or reply-driven sequences |
| Replace a device | TCP/virtual-serial simulator with recorded conversations, field rules and faults |
| Watch values | ANSI terminal with pop-out and live plots with Auto, Custom or plugin sources |
| Extend | User Python plugins for analysis, editing, metrics and explicitly enabled transforms |
| Observe USB HID | Read-only USBPcap/usbmon capture with report descriptor decoding |

TCP/serial traffic is a byte stream: read chunks are not necessarily complete
messages. Choose framing for your protocol. Probe is a host-side debug instrument;
it does not promise hard real-time timing or recover traffic lost before the OS
exposes it. See [traffic and captures](docs/traffic.md) and [testing](docs/testing.md).

## Start from source

Python 3.10+ with Tkinter is required. On Debian/Ubuntu, install `python3-tk` and
`python3-venv` first.

```sh
git clone --branch main https://github.com/mohsensafaei/Probe_Communication_Console.git
cd Probe_Communication_Console
python -m venv .venv
```

Activate the environment with `.venv\Scripts\activate` on Windows, or
`source .venv/bin/activate` on Linux, then:

```sh
python -m pip install -e .
python -m probe
```

The `probe` and `probe-gui` commands also start the application. No package is
currently published to PyPI; install from this repository or a release source archive.

For a first hardware-free check, select **USB / Serial**, enter `loop://`, connect
and send `Hello`. For a complete local TCP example, see [connections](docs/connections.md).

```sh
python -m probe --self-test
```

## Documentation

Start with the [documentation index](docs/README.md):

- [Install and update](docs/installation.md) · [Connections and proxies](docs/connections.md)
- [Traffic, Analyze and Capture Diff](docs/traffic.md) · [Terminal and plots](docs/terminal-and-plots.md)
- [Sequences](docs/sequences.md) · [Device simulator](docs/simulator.md)
- [HID monitoring](docs/hid.md) · [Python plugins](docs/plugins.md)
- [File formats](docs/formats.md) · [Troubleshooting](docs/troubleshooting.md)
- [Development](docs/development.md) · [Architecture](docs/architecture.md)
- [Testing](docs/testing.md) · [Build portable apps](docs/building.md) · [Release process](docs/releasing.md)

## Contribute

`main` is the canonical, cross-platform source branch, initially based on stable
Linux commit `3a31b4d4877089ce519c979976f98c6f571b2eeb`. The existing `linux` and
`windows` branches retain their historical layouts. New changes should target `main`.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
[Report a bug or suggest a feature](https://github.com/mohsensafaei/Probe_Communication_Console/issues/new/choose).
Please include a small reproducible capture with sensitive data removed.
For vulnerabilities, follow [SECURITY.md](SECURITY.md).

Probe code is [MIT licensed](LICENSE). Bundled dependencies, fonts and optional
USB capture components retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
The [changelog](CHANGELOG.md) records user-visible changes.
