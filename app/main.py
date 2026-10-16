# Riddle-FUVT
# Author : DanTheMan7777  |  https://github.com/DanRiddle
# License: Free-use only. See LICENSE.

from __future__ import annotations

import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path

import webview

import riddle_core as core


def _patch_pywebview_js_glob() -> None:
    # pywebview finds its own bridge scripts with glob(), and glob reads [ ] in
    # a path as a wildcard. Installed under a folder like D:\[Fivem-Store]\...,
    # it finds none of its scripts, injects an empty bridge, window.pywebview
    # never exists, and every button in the UI silently does nothing.
    # Escape the folder part before pywebview globs it.
    try:
        import glob as _glob
        import webview.util as _wvu
        js_dir = _wvu.get_js_dir()
    except Exception:
        return
    if not any(ch in js_dir for ch in "[]*?"):
        return

    original = _glob.glob

    def safe_glob(pattern, *args, **kwargs):
        if isinstance(pattern, str) and pattern.startswith(js_dir):
            pattern = _glob.escape(js_dir) + pattern[len(js_dir):]
        return original(pattern, *args, **kwargs)

    _wvu.glob = safe_glob


_patch_pywebview_js_glob()

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent

WEB_DIR = ROOT / "web"
SETTINGS_FILE = ROOT / "settings.json"
ICON_FILE = ROOT / "assets" / "Riddle-FUVT.ico"

_WINDOW = None


def _start_kwargs(verbose: bool) -> dict:
    kwargs = {"gui": "edgechromium", "debug": verbose}
    if not ICON_FILE.is_file():
        return kwargs
    try:
        accepted = inspect.signature(webview.start).parameters
    except (TypeError, ValueError):
        return kwargs
    if "icon" in accepted:
        kwargs["icon"] = str(ICON_FILE)
    return kwargs


def _win():
    if _WINDOW is not None:
        return _WINDOW
    windows = getattr(webview, "windows", None)
    return windows[0] if windows else None


def _folder_dialog_type():
    dialog = getattr(webview, "FileDialog", None)
    if dialog is not None and hasattr(dialog, "FOLDER"):
        return dialog.FOLDER
    return getattr(webview, "FOLDER_DIALOG", 20)


def _open_dialog_type():
    dialog = getattr(webview, "FileDialog", None)
    if dialog is not None and hasattr(dialog, "OPEN"):
        return dialog.OPEN
    return getattr(webview, "OPEN_DIALOG", 10)


def _save_dialog_type():
    dialog = getattr(webview, "FileDialog", None)
    if dialog is not None and hasattr(dialog, "SAVE"):
        return dialog.SAVE
    return getattr(webview, "SAVE_DIALOG", 30)


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


class Api:

    def __init__(self):
        self._vehicles = []
        self._settings = _load_settings()
        self._busy = threading.Lock()


    def _emit(self, event: str, payload: dict) -> None:
        window = _win()
        if not window:
            return
        try:
            window.evaluate_js(f"window.onPy({json.dumps(event)}, {json.dumps(payload)})")
        except Exception:
            pass

    def _run_async(self, fn) -> dict:
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "error": "A job is already running."}

        def worker():
            try:
                fn()
            finally:
                self._busy.release()

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "started": True}


    def app_info(self) -> dict:
        return {
            "name": core.APP_NAME,
            "version": core.APP_VERSION,
            "author": core.APP_AUTHOR,
            "github": core.APP_GITHUB,
            "gtautil": core.find_gtautil(self._settings.get("gtautil", "")),
            "settings": self._settings,
            "formats": [{"id": k, "label": v[2], "ext": v[1]} for k, v in core.EXPORTERS.items()],
        }


    def choose_folder(self, start: str = "") -> str | None:
        start = start or self._settings.get("last_folder", "") or os.path.expanduser("~")
        window = _win()
        if not window:
            return None
        result = window.create_file_dialog(_folder_dialog_type(), directory=start)
        if not result:
            return None
        return result[0]

    def choose_file(self) -> str | None:
        window = _win()
        if not window:
            return None
        result = window.create_file_dialog(
            _open_dialog_type(),
            directory=os.path.expanduser("~"),
            file_types=("Executable (*.exe)", "All files (*.*)"),
        )
        if not result:
            return None
        return result[0]

    def open_path(self, path: str) -> dict:
        try:
            if os.name == "nt":
                os.startfile(path)
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}


    def scan(self, folder: str, default_price: int = 0) -> dict:
        folder = str(folder or "")
        if not folder:
            return {"ok": False, "error": "No folder selected."}

        def job():
            self._emit("scan:start", {"folder": folder})
            try:
                def progress(done, total, label):
                    self._emit("scan:progress", {"done": done, "total": total, "label": label})

                result = core.scan_folder(folder, int(default_price or 0), progress)
            except Exception as exc:
                self._emit("scan:error", {"error": str(exc)})
                return

            self._vehicles = result["vehicles"]
            self._settings["last_folder"] = folder
            _save_settings(self._settings)

            rows = [
                [v["model"], v["name"], v["brand"], v["category"], v["type"], v["resource"], v["source"]]
                for v in self._vehicles
            ]
            self._emit("scan:done", {
                "rows": rows,
                "meta_count": result["meta_count"],
                "duplicates_removed": result["duplicates_removed"],
                "unreadable": len(result["unreadable"]),
                "folder": folder,
            })

        return self._run_async(job)

    def set_price(self, model: str, price) -> dict:
        try:
            price = int(price)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Price must be a number."}
        for v in self._vehicles:
            if v["model"] == model:
                v["price"] = price
                return {"ok": True}
        return {"ok": False, "error": "Unknown model."}

    def set_all_prices(self, price) -> dict:
        try:
            price = int(price)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Price must be a number."}
        for v in self._vehicles:
            v["price"] = price
        return {"ok": True, "count": len(self._vehicles)}


    def export(self, fmt: str, models=None) -> dict:
        if not self._vehicles:
            return {"ok": False, "error": "Nothing to export. Scan a folder first."}

        vehicles = self._vehicles
        if models:
            wanted = set(models)
            vehicles = [v for v in self._vehicles if v["model"] in wanted]
        if not vehicles:
            return {"ok": False, "error": "The current filter matches no vehicles."}

        try:
            content, ext = core.render_export(fmt, vehicles)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        window = _win()
        if not window:
            return {"ok": False, "error": "Window is not ready."}
        result = window.create_file_dialog(
            _save_dialog_type(),
            directory=self._settings.get("last_export", os.path.expanduser("~")),
            save_filename=f"riddle_vehicles.{ext}",
            file_types=(f"{ext.upper()} files (*.{ext})", "All files (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}

        selected = result[0] if isinstance(result, (tuple, list)) else result
        if not selected:
            return {"ok": False, "cancelled": True}

        path = Path(selected)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        self._settings["last_export"] = str(path.parent)
        _save_settings(self._settings)
        return {"ok": True, "path": str(path), "count": len(vehicles)}


    def locate_gtautil(self, custom: str = "") -> dict:
        path = core.find_gtautil(custom or self._settings.get("gtautil", ""))
        if path:
            self._settings["gtautil"] = path
            _save_settings(self._settings)
        return {"ok": bool(path), "path": path}

    def preview_build(self, folder: str) -> dict:
        try:
            probe = core.probe_folders(folder)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **probe}

    def get_gtautil(self) -> dict:
        result = core.download_gtautil(ROOT / "tools")
        if result.get("ok"):
            self._settings["gtautil"] = result["path"]
            _save_settings(self._settings)
        return result

    def build(self, folder: str, out_folder: str, prefix: str = "", options=None) -> dict:
        if not folder or not out_folder:
            return {"ok": False, "error": "Select both a source and an output folder."}
        if Path(out_folder).resolve() == Path(folder).resolve():
            return {"ok": False, "error": "Output folder must differ from the source folder."}

        gtautil = core.find_gtautil(self._settings.get("gtautil", ""))

        def job():
            self._emit("build:start", {"gtautil": gtautil})
            try:
                def progress(done, total, label):
                    self._emit("build:progress", {"done": done, "total": total, "label": label})

                result = core.build_batch(folder, out_folder, gtautil, prefix,
                                          options or {}, progress)
            except Exception as exc:
                self._emit("build:error", {"error": str(exc)})
                return
            self._emit("build:done", result)

        return self._run_async(job)

    def merge(self, folder: str, out_folder: str, name: str = "", options=None) -> dict:
        if not folder or not out_folder:
            return {"ok": False, "error": "Select both a source and an output folder."}
        if Path(out_folder).resolve() == Path(folder).resolve():
            return {"ok": False, "error": "Output folder must differ from the source folder."}

        gtautil = core.find_gtautil(self._settings.get("gtautil", ""))

        def job():
            self._emit("merge:start", {"gtautil": gtautil})
            try:
                def progress(done, total, label):
                    self._emit("merge:progress", {"done": done, "total": total, "label": label})

                result = core.merge_batch(folder, out_folder, gtautil, name,
                                          options or {}, progress)
            except Exception as exc:
                self._emit("merge:error", {"error": str(exc)})
                return
            self._emit("merge:done", result)

        return self._run_async(job)


def main() -> int:
    started = time.perf_counter()
    verbose = "--diag" in sys.argv

    api = Api()
    window = webview.create_window(
        f"{core.APP_NAME} v{core.APP_VERSION}  -  {core.APP_LONG_NAME}  -  by {core.APP_AUTHOR}",
        str(WEB_DIR / "index.html"),
        js_api=api,
        width=1280,
        height=820,
        min_size=(1040, 700),
        resizable=True,
        background_color="#07070A",
    )
    global _WINDOW
    _WINDOW = window

    if verbose:
        print(f"[diag] window created in {time.perf_counter() - started:.2f}s")

    try:
        webview.start(**_start_kwargs(verbose))
        return 0
    except Exception as exc:
        print(f"\n  WebView2 could not be started: {exc}\n")
        print("  Riddle-FUVT needs the Microsoft Edge WebView2 Runtime.")
        print("  It ships with Windows 10/11, but can be missing on trimmed installs.")
        print("  Get it here (Evergreen Standalone Installer):")
        print("  https://developer.microsoft.com/microsoft-edge/webview2/\n")
        print("  Falling back to the legacy renderer - expect it to be slow.\n")
        try:
            webview.start(debug=verbose)
            return 0
        except Exception as fallback_exc:
            print(f"  Could not start any renderer: {fallback_exc}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
