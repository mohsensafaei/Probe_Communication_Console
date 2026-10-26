"""Describe the two distinct ends of a preinstalled virtual serial pair."""
from dataclasses import dataclass
import os


def simulator_transports() -> tuple[str, ...]:
    return ("TCP socket", "Virtual COM pair" if os.name == "nt" else "Virtual serial (PTY)")


def port_identity(name: str) -> str:
    """Treat COM20 and the Windows device-path spelling as the same port."""
    return name.strip().removeprefix("\\\\.\\").casefold()


@dataclass(frozen=True)
class VirtualPair:
    probe: str
    application: str

    def validate(self, physical: str = "") -> None:
        if not self.probe.strip() or not self.application.strip():
            raise ValueError("Enter both ends of the installed virtual COM pair (for example COM20 and COM21).")
        names = [port_identity(self.probe), port_identity(self.application)]
        if physical:
            names.append(port_identity(physical))
        if len(set(names)) != len(names):
            raise ValueError("Physical, Probe-side and application-side ports must all be different.")
        if "auto pty" in names:
            raise ValueError("Choose an installed COM pair, or select the automatic PTY transport.")
