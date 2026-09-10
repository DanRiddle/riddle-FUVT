from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "Riddle-FUVT.ico"
VERSION_FILE = ROOT / "build" / "version_info.txt"

NAME = "Riddle-FUVT"
DESCRIPTION = "Riddle FiveM Ultimate Vehicle Tool"
AUTHOR = "DanTheMan7777"


def app_version() -> str:
    text = (ROOT / "riddle_core.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def write_version_info(version: str) -> Path:
    parts = (version.split(".") + ["0", "0", "0", "0"])[:4]
    quad = ", ".join(str(int(p) if p.isdigit() else 0) for p in parts)

    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad}), prodvers=({quad}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{AUTHOR}'),
        StringStruct('FileDescription', '{DESCRIPTION}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{NAME}'),
        StringStruct('LegalCopyright', 'Free use only. Selling this tool is not permitted.'),
        StringStruct('OriginalFilename', '{NAME}.exe'),
        StringStruct('ProductName', '{DESCRIPTION}'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return VERSION_FILE


def main() -> int:
    if shutil.which("pyinstaller") is None:
        try:
            import PyInstaller
        except ImportError:
            print("PyInstaller is not installed. In the app's environment:\n"
                  "    .venv\\Scripts\\python -m pip install pyinstaller")
            return 1

    if not ICON.is_file():
        print(f"missing {ICON.relative_to(ROOT)} - run scripts/make_icon.py first")
        return 1

    version = app_version()
    version_info = write_version_info(version)
    separator = ";" if sys.platform == "win32" else ":"

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        "--onedir",
        "--windowed",
        "--icon", str(ICON),
        "--version-file", str(version_info),
        "--add-data", f"{ROOT / 'web'}{separator}web",
        "--add-data", f"{ROOT / 'data'}{separator}data",
        "--add-data", f"{ROOT / 'assets'}{separator}assets",
        "--collect-all", "py7zr",
        str(ROOT / "app" / "main.py"),
    ]

    print(f"Building {NAME} {version}...\n")
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        return result.returncode

    out = ROOT / "dist" / NAME
    print(f"\n  Built: {out}")
    print("  Zip that folder for release. The .exe alone will not run.")
    print("\n  An unsigned .exe will trip SmartScreen. Publish the zip's")
    print("  SHA-256 alongside it so people can check what they downloaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
