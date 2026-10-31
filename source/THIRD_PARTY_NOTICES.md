# Third-party components

Runtime: CPython and Tcl/Tk (PSF/Tcl/Tk licenses), pySerial 3.5 (BSD), pyte 0.8.2 (LGPLv3) and wcwidth 0.2.13 (MIT). Portable bundles include available license files under `licenses`. Build tool: PyInstaller (GPL with bootloader exception), with its hooks and build dependencies.

The pyte and wcwidth source is included in portable bundles under `third-party-source`. The complete Probe source and build scripts accompany this release. To use a modified/replacement library, install it in the source environment and run/rebuild Probe with the provided scripts; Probe itself uses the MIT license.

* https://docs.python.org/3/license.html
* https://www.tcl-lang.org/software/tcltk/license.html
* https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt
* https://pyinstaller.org/en/stable/license.html
* https://github.com/selectel/pyte/blob/0.8.2/LICENSE
* https://github.com/jquast/wcwidth/blob/0.2.13/LICENSE

Bundled fonts: Rajdhani (Indian Type Foundry), Michroma (Vernon Adams), and Share Tech Mono (Carrois Type Design), under the SIL Open Font License 1.1. Unmodified TTF files and their full copyright/license notices are in `assets/fonts` and in the frozen bundle's resources; the portable ZIP also includes the font licenses under `licenses`.

* https://github.com/google/fonts/tree/main/ofl/rajdhani
* https://github.com/google/fonts/tree/main/ofl/michroma
* https://github.com/google/fonts/tree/main/ofl/sharetechmono

Probe uses an original hardware test-probe emblem and independently drawn instrument workbench interface. No third-party product branding, artwork or proprietary font is bundled. Hercules and SSCOM are referenced for workflow comparison only; their code, icons and binaries are not incorporated into Probe.


HID Monitor optional Windows components:

* HIDAPI 0.15.0 (Python bindings and native HIDAPI code), used for HID descriptor
  metadata only. Distributed under its BSD license option; available license
  texts are included in portable `licenses/hidapi` resources.
  https://github.com/trezor/cython-hidapi and https://github.com/libusb/hidapi
* USBPcap 1.5.4.0: original installer plus corresponding source archive under
  `drivers/windows`; GPLv2 driver and BSD 2-Clause command-line tool, by Tomasz Moń
  and contributors. Full license texts and exact installer SHA-256 are included.
  https://github.com/desowin/usbpcap/releases/tag/1.5.4.0
  Probe invokes the separate installed capture executable; it does not link to
  the driver or command-line program. The Windows driver is not installed or
  included in Linux portable archives. Linux uses its host kernel's usbmon.
