"""Build the local SwiftUI application without a web server."""

import plistlib
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
app = root / "dist" / "Učna priprava.app" / "Contents"
(app / "MacOS").mkdir(parents=True, exist_ok=True)
(app / "Resources").mkdir(exist_ok=True)
(app / "Resources" / "Workspace.txt").write_text(str(root))
(app / "Info.plist").write_bytes(
    plistlib.dumps(
        {
            "CFBundleExecutable": "StudyApp",
            "CFBundleIdentifier": "si.remarkable.study.desktop",
            "CFBundleName": "Učna priprava",
            "CFBundleDisplayName": "Učna priprava",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "LSMinimumSystemVersion": "14.0",
            "NSHighResolutionCapable": True,
        }
    )
)
subprocess.run(
    [
        "xcrun",
        "swiftc",
        "-parse-as-library",
        "-O",
        "-target",
        "arm64-apple-macos14",
        "-module-cache-path",
        str(root / "tmp" / "swift-cache"),
        str(root / "macos" / "StudyApp.swift"),
        "-o",
        str(app / "MacOS" / "StudyApp"),
    ],
    check=True,
)
subprocess.run(
    ["codesign", "--force", "--deep", "--sign", "-", str(app.parent)], check=True
)
print(app.parent)
