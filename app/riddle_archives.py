# Riddle-FUVT - archive layer
# Author : DanTheMan7777  |  https://github.com/DanRiddle
# License: Free-use only. See LICENSE.

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

try:
    import py7zr
except ImportError:
    py7zr = None


MAX_TOTAL_BYTES = 20 * 1024 ** 3
MAX_ENTRIES = 200_000
MAX_DEPTH = 3
EXTRACT_TIMEOUT = 1800
COPY_CHUNK = 1024 * 1024

ARCHIVE_EXT = frozenset({".zip", ".rar", ".7z"})

SKIP_DIRS = frozenset({
    ".git", ".svn", ".idea", ".vscode", "__pycache__", "node_modules",
    "$recycle.bin", "system volume information",
})

SEVENZIP_PAGE = "https://www.7-zip.org/download.html"
PY7ZR_HINT = "pip install py7zr"

SEVENZIP_CANDIDATES = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]
UNRAR_CANDIDATES = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
]


class ArchiveError(Exception):
    pass


_MAGIC = [
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"PK\x07\x08", "zip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07\x01\x00", "rar"),
    (b"Rar!\x1a\x07\x00", "rar"),
]


def sniff(path) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return "none"
    for magic, name in _MAGIC:
        if head.startswith(magic):
            return name
    return "none"


def _which(name: str, candidates: list) -> str:
    found = shutil.which(name)
    if found:
        return found
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


def find_sevenzip() -> str:
    return _which("7z", SEVENZIP_CANDIDATES)


def find_unrar() -> str:
    return _which("UnRAR", UNRAR_CANDIDATES) or _which("unrar", UNRAR_CANDIDATES)


def backends() -> dict:
    sevenzip = find_sevenzip()
    unrar = find_unrar()
    return {
        "zip": True,
        "7z": py7zr is not None,
        "rar": bool(sevenzip or unrar),
        "sevenzip": sevenzip,
        "unrar": unrar,
        "py7zr": py7zr is not None,
    }


def probe(path) -> dict:
    path = Path(path)
    fmt = sniff(path)
    if fmt == "none":
        return {"format": "none", "supported": False,
                "reason": "not a zip, rar or 7z archive"}

    if fmt == "zip":
        return {"format": "zip", "supported": True, "reason": ""}

    if fmt == "7z":
        if py7zr is None:
            return {"format": "7z", "supported": False,
                    "reason": f"7z support needs py7zr ({PY7ZR_HINT})"}
        return {"format": "7z", "supported": True, "reason": ""}

    if find_sevenzip() or find_unrar():
        return {"format": "rar", "supported": True, "reason": ""}
    return {"format": "rar", "supported": False,
            "reason": f"rar needs 7-Zip installed ({SEVENZIP_PAGE}), or WinRAR"}


def find_archives(root) -> list:
    root = Path(root)
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part.lower() in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in ARCHIVE_EXT:
            continue
        if sniff(path) != "none":
            found.append(path)
    return found


_DRIVE = re.compile(r"^[A-Za-z]:")


def safe_member_path(out_dir: Path, name: str):
    if not name:
        return None
    cleaned = name.replace("\\", "/")
    if cleaned.startswith("/") or cleaned.startswith("//") or _DRIVE.match(cleaned):
        return None
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    dest = out_dir / Path(*parts)
    try:
        resolved = dest.resolve()
        base = out_dir.resolve()
    except OSError:
        return None
    if resolved != base and not resolved.is_relative_to(base):
        return None
    return dest


class _Budget:

    def __init__(self, max_bytes: int = MAX_TOTAL_BYTES, max_entries: int = MAX_ENTRIES):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.bytes = 0
        self.entries = 0

    def spend(self, count: int) -> None:
        self.bytes += count
        if self.bytes > self.max_bytes:
            cap = (f"{self.max_bytes / 1024 ** 3:.0f} GB"
                   if self.max_bytes >= 1024 ** 3
                   else f"{self.max_bytes / 1024 ** 2:.0f} MB")
            raise ArchiveError(
                f"aborted: uncompressed size passed the {cap} cap - this looks "
                f"like a decompression bomb"
            )

    def add_entry(self) -> None:
        self.entries += 1
        if self.entries > self.max_entries:
            raise ArchiveError(
                f"aborted: more than {self.max_entries} entries in one archive"
            )


def _zip_is_symlink(info: zipfile.ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _extract_zip(path: Path, out_dir: Path, budget: _Budget, problems: list,
                 progress=None) -> list:
    written = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        total = len(infos)
        for index, info in enumerate(infos, 1):
            if progress:
                progress(index, total, info.filename)
            if info.flag_bits & 0x1:
                problems.append(f"{info.filename}: encrypted, skipped")
                continue
            if _zip_is_symlink(info):
                problems.append(f"{info.filename}: symlink, skipped")
                continue

            dest = safe_member_path(out_dir, info.filename)
            if dest is None:
                problems.append(
                    f"{info.filename}: entry points outside the output folder, refused"
                )
                continue
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue

            budget.add_entry()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(dest, "wb") as out:
                while True:
                    chunk = src.read(COPY_CHUNK)
                    if not chunk:
                        break
                    budget.spend(len(chunk))
                    out.write(chunk)
            written.append(dest)
    return written


def _extract_7z(path: Path, out_dir: Path, budget: _Budget, problems: list,
                progress=None) -> list:
    if py7zr is None:
        raise ArchiveError(f"7z support needs py7zr ({PY7ZR_HINT})")

    try:
        with py7zr.SevenZipFile(path, mode="r") as archive:
            if archive.needs_password():
                raise ArchiveError("archive is password protected")

            entries = archive.list()
            declared = 0
            for entry in entries:
                name = getattr(entry, "filename", "") or ""
                if getattr(entry, "is_directory", False):
                    continue
                if safe_member_path(out_dir, name) is None:
                    raise ArchiveError(
                        f"refused: entry '{name}' points outside the output folder"
                    )
                budget.add_entry()
                declared += int(getattr(entry, "uncompressed", 0) or 0)
            budget.spend(declared)

            if progress:
                progress(0, len(entries), path.name)
            archive.extractall(path=str(out_dir))
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError(f"{type(exc).__name__}: {exc}") from exc

    return _sweep_output(out_dir, budget, problems, declared_already_spent=declared)


def _run(cmd, timeout=EXTRACT_TIMEOUT):
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, creationflags=flags)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "the unpacker timed out"
    except OSError as exc:
        return -1, str(exc)


def _listing_7z(tool: str, path: Path) -> tuple:
    code, output = _run([tool, "l", "-slt", "-y", str(path)], timeout=300)
    if code != 0:
        return [], 0, False
    names, total = [], 0
    in_entries = False
    for line in output.splitlines():
        if line.startswith("----------"):
            in_entries = True
            continue
        if not in_entries:
            continue
        if line.startswith("Path = "):
            names.append(line[7:].strip())
        elif line.startswith("Size = "):
            try:
                total += int(line[7:].strip() or 0)
            except ValueError:
                pass
    return names, total, bool(names)


def _listing_unrar(tool: str, path: Path) -> tuple:
    code, output = _run([tool, "lt", "-y", str(path)], timeout=300)
    if code != 0:
        return [], 0, False
    names, total = [], 0
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name: "):
            names.append(stripped[6:].strip())
        elif stripped.startswith("Size: "):
            try:
                total += int(stripped[6:].strip() or 0)
            except ValueError:
                pass
    return names, total, bool(names)


def _extract_rar(path: Path, out_dir: Path, budget: _Budget, problems: list,
                 progress=None) -> list:
    sevenzip = find_sevenzip()
    unrar = "" if sevenzip else find_unrar()
    if not sevenzip and not unrar:
        raise ArchiveError(
            f"rar needs 7-Zip installed ({SEVENZIP_PAGE}), or WinRAR"
        )

    if sevenzip:
        names, declared, listed = _listing_7z(sevenzip, path)
        cmd = [sevenzip, "x", "-y", "-bd", f"-o{out_dir}", str(path)]
        tool_name = "7-Zip"
    else:
        names, declared, listed = _listing_unrar(unrar, path)
        cmd = [unrar, "x", "-y", "-o+", str(path), f"{out_dir}{os.sep}"]
        tool_name = "UnRAR"

    if listed:
        for name in names:
            if safe_member_path(out_dir, name) is None:
                raise ArchiveError(
                    f"refused: entry '{name}' points outside the output folder"
                )
        budget.spend(declared)
    else:
        problems.append(
            f"could not list {path.name} before extracting - size and path "
            f"checks were applied afterwards instead"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(0, 1, path.name)
    code, output = _run(cmd)
    if code not in (0, 1):
        raise ArchiveError(f"{tool_name} failed: {output.strip()[:400]}")
    if code == 1:
        problems.append(f"{tool_name} reported warnings on {path.name}")

    return _sweep_output(out_dir, budget, problems,
                         declared_already_spent=declared if listed else 0)


def _sweep_output(out_dir: Path, budget: _Budget, problems: list,
                  declared_already_spent: int = 0) -> list:
    base = out_dir.resolve()
    written = []
    actual = 0
    for path in sorted(out_dir.rglob("*")):
        if path.is_symlink():
            problems.append(f"{path.name}: symlink in archive, removed")
            try:
                path.unlink()
            except OSError:
                pass
            continue
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(base):
            problems.append(f"{path.name}: resolved outside the output folder, removed")
            try:
                path.unlink()
            except OSError:
                pass
            continue
        actual += path.stat().st_size
        written.append(path)

    remainder = actual - declared_already_spent
    if remainder > 0:
        budget.spend(remainder)
    return written


def _extract_nested(out_dir: Path, budget: _Budget, problems: list,
                    depth: int, progress=None) -> list:
    written = []
    if depth >= MAX_DEPTH:
        return written

    inner = [p for p in sorted(out_dir.rglob("*"))
             if p.is_file() and p.suffix.lower() in ARCHIVE_EXT and sniff(p) != "none"]
    for archive in inner:
        info = probe(archive)
        if not info["supported"]:
            problems.append(f"nested {archive.name}: {info['reason']}")
            continue
        target = archive.parent / f"{archive.stem}_unpacked"
        try:
            written.extend(_dispatch(info["format"], archive, target, budget,
                                     problems, progress))
            written.extend(_extract_nested(target, budget, problems, depth + 1, progress))
        except ArchiveError as exc:
            problems.append(f"nested {archive.name}: {exc}")
            continue
        try:
            archive.unlink()
        except OSError:
            pass
    return written


def _dispatch(fmt: str, path: Path, out_dir: Path, budget: _Budget,
              problems: list, progress=None) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        return _extract_zip(path, out_dir, budget, problems, progress)
    if fmt == "7z":
        return _extract_7z(path, out_dir, budget, problems, progress)
    if fmt == "rar":
        return _extract_rar(path, out_dir, budget, problems, progress)
    raise ArchiveError(f"unsupported format: {fmt}")


def _content_root(out_dir: Path) -> Path:
    current = out_dir
    for _ in range(4):
        try:
            children = [c for c in current.iterdir()]
        except OSError:
            return current
        if len(children) == 1 and children[0].is_dir():
            current = children[0]
            continue
        return current
    return current


def extract(path, out_dir, progress=None, max_bytes: int = MAX_TOTAL_BYTES) -> dict:
    path = Path(path)
    out_dir = Path(out_dir)
    problems: list = []
    budget = _Budget(max_bytes=max_bytes)

    info = probe(path)
    if not info["supported"]:
        return {"ok": False, "files": [], "root": str(out_dir),
                "problems": problems, "format": info["format"],
                "error": info["reason"]}

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        files = _dispatch(info["format"], path, out_dir, budget, problems, progress)
        files.extend(_extract_nested(out_dir, budget, problems, 0, progress))
    except ArchiveError as exc:
        return {"ok": False, "files": [], "root": str(out_dir),
                "problems": problems, "format": info["format"], "error": str(exc)}
    except (OSError, zipfile.BadZipFile, struct.error) as exc:
        return {"ok": False, "files": [], "root": str(out_dir),
                "problems": problems, "format": info["format"],
                "error": f"{type(exc).__name__}: {exc}"}

    if not files:
        return {"ok": False, "files": [], "root": str(out_dir),
                "problems": problems, "format": info["format"],
                "error": "archive contained no extractable files"}

    return {
        "ok": True,
        "files": [str(f) for f in files],
        "root": str(_content_root(out_dir)),
        "problems": problems,
        "format": info["format"],
        "bytes": budget.bytes,
    }
