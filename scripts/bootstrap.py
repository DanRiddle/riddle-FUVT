from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
STAMP = VENV / ".ready"
REQUIREMENTS = ROOT / "requirements.txt"

MIN_PYTHON = (3, 10)

OPTIONAL = ["py7zr>=0.20"]

WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def fail(message: str, *extra: str) -> int:
    print(f"\n  Setup stopped: {message}\n", flush=True)
    for line in extra:
        print(f"  {line}", flush=True)
    if extra:
        print(flush=True)
    return 1


def venv_python(windowed: bool = False) -> Path:
    if os.name == "nt":
        name = "pythonw.exe" if windowed else "python.exe"
        return VENV / "Scripts" / name
    return VENV / "bin" / "python"


def check_python() -> int | None:
    if sys.version_info < MIN_PYTHON:
        return fail(
            f"this is Python {sys.version.split()[0]}, and Riddle-FUVT needs "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            "Install a current Python from https://www.python.org/downloads/",
            'and tick "Add python.exe to PATH" in the installer.',
        )
    return None


def check_webview2() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""

    places = [
        (winreg.HKEY_LOCAL_MACHINE,
         rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE,
         rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
        (winreg.HKEY_CURRENT_USER,
         rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"),
    ]
    for hive, path in places:
        try:
            with winreg.OpenKey(hive, path) as key:
                version, _kind = winreg.QueryValueEx(key, "pv")
                if version and version != "0.0.0.0":
                    return str(version)
        except OSError:
            continue
    return ""


def requirement_lines() -> list:
    if not REQUIREMENTS.exists():
        return []
    lines = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def wanted_state() -> dict:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "requirements": requirement_lines(),
        "optional": OPTIONAL,
    }


def is_ready() -> bool:
    if not venv_python().exists():
        return False
    try:
        return json.loads(STAMP.read_text(encoding="utf-8")) == wanted_state()
    except (OSError, ValueError):
        return False


def create_venv() -> int | None:
    if venv_python().exists():
        return None
    say("First run - building a private Python environment. One moment.")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    except Exception as exc:
        return fail(
            f"could not create the environment ({type(exc).__name__}: {exc}).",
            "If Python came from the Microsoft Store, install it from",
            "python.org instead - the Store build restricts what scripts may do.",
        )
    if not venv_python().exists():
        return fail("the environment was created but has no Python in it.",
                    "Delete the .venv folder and try again.")
    return None


def pip_install(args: list, label: str, required: bool) -> int | None:
    command = [str(venv_python()), "-m", "pip", "install",
               "--disable-pip-version-check", "--no-input", *args]
    try:
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                                text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if not required:
            say(f"optional: {label} not installed ({exc})")
            return None
        return fail(f"could not run pip ({exc}).")

    if result.returncode == 0:
        return None
    if not required:
        say(f"optional: {label} could not be installed - .7z archives will be "
            f"reported as unsupported")
        return None

    lines = (result.stdout + result.stderr).strip().splitlines()
    tail = [line for line in lines if "ERROR" in line][:6] or lines[-6:]
    return fail(
        f"installing {label} failed.",
        "pip said:",
        *[f"    {line}" for line in tail],
        "",
        "If this is a network or proxy problem, fix that and run this again.",
    )


def install_everything() -> int | None:
    say("Installing what the app needs...")
    problem = pip_install(["-r", str(REQUIREMENTS)], "the required packages", True)
    if problem:
        return problem
    pip_install(OPTIONAL, "py7zr (optional, for .7z archives)", False)
    return None


def make_shortcut() -> None:
    if os.name != "nt":
        return
    script = ROOT / "scripts" / "make_shortcut.py"
    if not script.is_file():
        return
    try:
        subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main() -> int:
    repair = "--repair" in sys.argv

    problem = check_python()
    if problem:
        return problem

    if repair and VENV.exists():
        say("Repair: removing the existing environment.")
        shutil.rmtree(VENV, ignore_errors=True)

    if is_ready():
        print(str(venv_python(windowed=True)))
        return 0

    problem = create_venv() or install_everything()
    if problem:
        return problem

    try:
        STAMP.write_text(json.dumps(wanted_state(), indent=2), encoding="utf-8")
    except OSError:
        pass

    make_shortcut()

    version = check_webview2()
    if os.name == "nt" and not version:
        say("")
        say("Note: the Microsoft Edge WebView2 runtime was not found.")
        say("Riddle-FUVT needs it to draw its window. It ships with Windows 10")
        say("and 11 but is missing on some trimmed installs. Get it here:")
        say(f"  {WEBVIEW2_URL}")
        say("")

    say("Ready.")
    print(str(venv_python(windowed=True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
