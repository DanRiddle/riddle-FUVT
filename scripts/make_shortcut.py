from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "Riddle-FUVT.bat"
ICON = ROOT / "assets" / "Riddle-FUVT.ico"

DESCRIPTION = "Riddle FiveM Ultimate Vehicle Tool"

LINK_NAME = "Riddle FiveM Ultimate Vehicle Tool"

WINDOW_MINIMISED = 7


def ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def write_shortcut(path: Path) -> str:
    if os.name != "nt":
        return "shortcuts are a Windows feature"
    if not TARGET.is_file():
        return f"{TARGET.name} is missing"

    icon = f"{ICON},0" if ICON.is_file() else str(TARGET)
    script = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$shell = New-Object -ComObject WScript.Shell",
        f"$link = $shell.CreateShortcut({ps_quote(path)})",
        f"$link.TargetPath = {ps_quote(TARGET)}",
        f"$link.WorkingDirectory = {ps_quote(ROOT)}",
        f"$link.IconLocation = {ps_quote(icon)}",
        f"$link.Description = {ps_quote(DESCRIPTION)}",
        f"$link.WindowStyle = {WINDOW_MINIMISED}",
        "$link.Save()",
    ])

    handle = tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                         encoding="utf-8")
    try:
        handle.write(script)
        handle.close()
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", handle.name],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not run PowerShell ({exc})"
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return detail[0] if detail else f"PowerShell exited {result.returncode}"
    if not path.exists():
        return "PowerShell reported success but no shortcut appeared"
    return ""


def desktop_dir() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _kind = winreg.QueryValueEx(handle, "Desktop")
        path = Path(os.path.expandvars(value))
        if path.is_dir():
            return path
    except (ImportError, OSError):
        pass
    fallback = Path.home() / "Desktop"
    return fallback if fallback.is_dir() else None


def main() -> int:
    if os.name != "nt":
        print("  Shortcuts are a Windows feature - nothing to do here.")
        return 0

    problems = []

    local = ROOT / f"{LINK_NAME}.lnk"
    reason = write_shortcut(local)
    if reason:
        problems.append(f"app folder: {reason}")
    else:
        print(f"  Created '{local.stem}' in the app folder.")

    if "--desktop" in sys.argv:
        desktop = desktop_dir()
        if desktop is None:
            problems.append("desktop: could not find the Desktop folder")
        else:
            reason = write_shortcut(desktop / f"{LINK_NAME}.lnk")
            if reason:
                problems.append(f"desktop: {reason}")
            else:
                print(f"  Created '{LINK_NAME}' on the Desktop.")

    for problem in problems:
        print(f"  Could not create a shortcut - {problem}")
    if problems:
        print("  Not a real problem: Riddle-FUVT.bat still runs the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
