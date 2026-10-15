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

ASUS PC Probe II is a visual reference for the original Probe instrument-panel layout. No ASUS logo, proprietary font, artwork or program code is bundled. Hercules and SSCOM are referenced for workflow comparison only; their code, icons and binaries are not incorporated into Probe.
