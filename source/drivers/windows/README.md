# Offline USBPcap prerequisite — Windows

Unmodified official USBPcap 1.5.4.0 installer, x86/x64, downloaded before packaging.
Source: https://github.com/desowin/usbpcap/releases/tag/1.5.4.0
Installer: https://github.com/desowin/usbpcap/releases/download/1.5.4.0/USBPcapSetup-1.5.4.0.exe
SHA-256: 87a7edf9bbbcf07b5f4373d9a192a6770d2ff3add7aa1e276e82e38582ccb622

The corresponding upstream tag is included as USBPcap-1.5.4.0-source.zip.
Driver license: GPLv2; command-line program: BSD 2-Clause. Full license texts
are included. Installer/source are distributed alongside Probe, not linked into it.
USBPcap copyright (c) 2013–2020 Tomasz Moń and contributors.

Use HID Monitor → Install USBPcap (offline). Setup uses its original interactive
license/install pages and requests UAC only when invoked. A Windows restart may
be needed before capture works. Probe never downloads or silently installs a driver,
never restarts Windows, and does not replace the HID device's existing driver.
Ordinary Probe startup does not require administrator permission.

Linux uses the host kernel's usbmon module; a Windows driver is not installed there.
Kernel modules must match the running kernel, so no portable usbmon.ko is supplied.
