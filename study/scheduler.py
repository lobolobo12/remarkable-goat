"""macOS LaunchAgent: hourly checks, plus a run at login."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "si.remarkable.study"


def configuration(store):
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(Path(sys.executable).absolute()),
            "-m",
            "study.cli",
            "--root",
            str(store.root),
            "run",
        ],
        "WorkingDirectory": str(store.root),
        "RunAtLoad": True,
        "StartInterval": 3600,
        "ProcessType": "Background",
        "ThrottleInterval": 300,
        "StandardOutPath": str(store.private / "scheduler.log"),
        "StandardErrorPath": str(store.private / "scheduler-error.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
        },
        "Umask": 63,
    }


def install(store):
    if sys.platform != "darwin":
        raise RuntimeError("This scheduler installer requires macOS.")
    destination = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = plistlib.dumps(configuration(store))
    staged = store.private / f"{LABEL}.plist"
    staged.write_bytes(content)
    os.chmod(staged, 0o600)
    target = f"gui/{os.getuid()}/{LABEL}"
    subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
    destination.write_bytes(content)
    os.chmod(destination, 0o600)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)],
        check=True,
        capture_output=True,
    )
    return str(destination)


def status():
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"installed": result.returncode == 0}
