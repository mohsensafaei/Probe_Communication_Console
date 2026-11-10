# Security policy

Security fixes target `main` and the latest stable release. Older release lines
are not maintained independently. There is no guaranteed response time or support SLA.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/mohsensafaei/Probe_Communication_Console/security/advisories/new)
when enabled. Otherwise, use a private contact listed on the maintainer's
[profile](https://github.com/mohsensafaei). If neither route is available, open an
issue asking for a private reporting channel without disclosing exploit details.
Include the affected version, reproduction steps, impact and a minimal sanitized sample.
Do not attach credentials, payment data or private traffic to public issues.

## Trust boundaries

Probe normally runs as the current user. Python plugins are executable code with
that user's file and network permissions; worker isolation is not a security sandbox.
Only load plugins you trust. HID capture uses a separate privileged helper when
needed; plugins do not execute in that helper. Capture files may contain private
data. Listening sockets should bind to loopback unless remote access is intended.
Bundled USBPcap installers are hash-checked before installation.
