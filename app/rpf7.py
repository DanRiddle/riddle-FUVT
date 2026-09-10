# Riddle-FUVT - native RPF7 reader
# Author : DanTheMan7777  |  https://github.com/DanRiddle
# License: Free-use only. See LICENSE.

from __future__ import annotations

import struct
import zlib
from pathlib import Path

RPF7_MAGIC = 0x52504637
RSC7_MAGIC = b"RSC7"

ENC_NONE = 0x00000000
ENC_OPEN = 0x4E45504F
ENC_AES = 0x0FFFFFF9
ENC_NG = 0x0FEFFFFF

ENC_NAMES = {
    ENC_NONE: "none",
    ENC_OPEN: "open",
    ENC_AES: "aes",
    ENC_NG: "ng",
}

DIR_MARKER = 0x7FFFFF00

RESOURCE_EXT = frozenset({
    ".yft", ".ytd", ".ydr", ".ydd", ".ybn", ".ycd", ".ynv",
    ".yed", ".ypt", ".ytyp", ".ymap", ".ymt", ".yvr", ".ywr",
})
TEXT_EXT = frozenset({".meta", ".xml"})


class RpfError(Exception):
    pass


class NeedsKeysError(RpfError):

    def __init__(self, encryption: str):
        super().__init__(
            f"archive uses {encryption.upper()} encryption; "
            "the GTA V keys are needed, so gtautil has to handle this one"
        )
        self.encryption = encryption


class RpfEntry:
    __slots__ = ("kind", "name", "name_offset", "size", "offset",
                 "uncompressed_size", "encrypted", "system_flags",
                 "graphics_flags", "first_child", "child_count", "path",
                 "synthesized_header")

    def __init__(self, kind):
        self.kind = kind
        self.name = ""
        self.path = ""
        self.name_offset = 0
        self.size = 0
        self.offset = 0
        self.uncompressed_size = 0
        self.encrypted = False
        self.system_flags = 0
        self.graphics_flags = 0
        self.first_child = 0
        self.child_count = 0
        self.synthesized_header = False

    @property
    def is_dir(self):
        return self.kind == "dir"

    def stored_size(self):
        return self.size if self.size else self.uncompressed_size

    def __repr__(self):
        return f"<RpfEntry {self.kind} {self.path or self.name!r} size={self.size}>"


def _read_name(names: bytes, offset: int) -> str:
    if offset >= len(names):
        return ""
    end = names.find(b"\x00", offset)
    if end < 0:
        end = len(names)
    return names[offset:end].decode("utf-8", "replace")[:256]


def _version_from_flags(system_flags: int, graphics_flags: int) -> int:
    return (((system_flags >> 28) & 0xF) << 4) | ((graphics_flags >> 28) & 0xF)


class RpfArchive:

    def __init__(self, handle, start: int = 0, name: str = "", size: int = 0):
        self.handle = handle
        self.start = start
        self.name = name
        self.size = size
        self.entries = []
        self.encryption = ENC_NONE
        self._read_header()


    def _read_header(self):
        self.handle.seek(self.start)
        head = self.handle.read(16)
        if len(head) < 16:
            raise RpfError("file is too small to be an RPF archive")

        version, entry_count, names_length, encryption = struct.unpack("<4I", head)
        if version != RPF7_MAGIC:
            raise RpfError("not an RPF7 archive (bad magic) - GTA V archives only")

        self.encryption = encryption
        if encryption in (ENC_AES, ENC_NG):
            raise NeedsKeysError(ENC_NAMES[encryption])
        if encryption not in (ENC_NONE, ENC_OPEN):
            raise NeedsKeysError("unknown")

        if entry_count == 0 or entry_count > 4_000_000:
            raise RpfError(f"implausible entry count ({entry_count})")

        entries_blob = self.handle.read(entry_count * 16)
        names_blob = self.handle.read(names_length)
        if len(entries_blob) < entry_count * 16:
            raise RpfError("archive is truncated (entry table incomplete)")

        for index in range(entry_count):
            self.entries.append(self._parse_entry(entries_blob, index * 16, names_blob))

        self._build_paths()

    @staticmethod
    def _parse_entry(blob: bytes, at: int, names: bytes) -> RpfEntry:
        low, high, third, fourth = struct.unpack_from("<4I", blob, at)
        packed = low | (high << 32)

        if high == DIR_MARKER:
            entry = RpfEntry("dir")
            entry.name_offset = low
            entry.first_child = third
            entry.child_count = fourth
        elif high & 0x80000000:
            entry = RpfEntry("resource")
            entry.name_offset = packed & 0xFFFF
            entry.size = (packed >> 16) & 0xFFFFFF
            entry.offset = (packed >> 40) & 0x7FFFFF
            entry.system_flags = third
            entry.graphics_flags = fourth
        else:
            entry = RpfEntry("binary")
            entry.name_offset = packed & 0xFFFF
            entry.size = (packed >> 16) & 0xFFFFFF
            entry.offset = (packed >> 40) & 0xFFFFFF
            entry.uncompressed_size = third
            entry.encrypted = fourth == 1

        entry.name = _read_name(names, entry.name_offset)
        return entry

    def _build_paths(self):
        root = self.entries[0]
        if not root.is_dir:
            raise RpfError("first entry is not the root directory")
        root.path = ""

        stack = [root]
        seen = set()
        while stack:
            node = stack.pop()
            start = node.first_child
            end = node.first_child + node.child_count
            if end > len(self.entries):
                continue
            for index in range(start, end):
                if index in seen:
                    continue
                seen.add(index)
                child = self.entries[index]
                child.path = f"{node.path}/{child.name}".lstrip("/")
                if child.is_dir:
                    stack.append(child)


    def files(self):
        return [e for e in self.entries if not e.is_dir and e.name]

    def read(self, entry: RpfEntry) -> bytes:
        if entry.is_dir:
            raise RpfError("cannot read a directory entry")

        base = self.start + entry.offset * 512

        if entry.kind == "binary":
            length = entry.stored_size()
            if length == 0:
                return b""
            if entry.encrypted:
                raise NeedsKeysError("aes-or-ng")
            self.handle.seek(base)
            raw = self.handle.read(length)
            if entry.size:
                return _inflate(raw)
            return raw

        if entry.size == 0:
            return b""
        self.handle.seek(base)
        raw = self.handle.read(entry.size)
        if raw[:4] == RSC7_MAGIC:
            return raw
        entry.synthesized_header = True
        version = _version_from_flags(entry.system_flags, entry.graphics_flags)
        header = RSC7_MAGIC + struct.pack(
            "<3I", version, entry.system_flags, entry.graphics_flags
        )
        return header + raw[16:]

    def nested_archives(self):
        return [e for e in self.files()
                if e.kind == "binary" and e.name.lower().endswith(".rpf")]

    def open_nested(self, entry: RpfEntry) -> "RpfArchive":
        return RpfArchive(
            self.handle,
            start=self.start + entry.offset * 512,
            name=entry.name,
            size=entry.stored_size(),
        )


def _inflate(raw: bytes) -> bytes:
    try:
        return zlib.decompress(raw, -15)
    except zlib.error:
        obj = zlib.decompressobj(-15)
        try:
            return obj.decompress(raw)
        except zlib.error as exc:
            raise RpfError(f"could not decompress entry: {exc}") from exc


def verify(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if not data:
        return "empty"
    if ext in RESOURCE_EXT:
        if data[:4] != RSC7_MAGIC:
            return f"expected RSC7 header, got {data[:4]!r}"
        probe = zlib.decompressobj(-15)
        try:
            probe.decompress(data[16:16384])
        except zlib.error as exc:
            return f"resource body is not valid deflate ({exc})"
        return ""
    if ext in TEXT_EXT:
        head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
        if head != b"<":
            return "does not look like XML"
        return ""
    return ""


def extract_all(rpf_path, out_dir, max_depth: int = 6, on_file=None) -> dict:
    rpf_path = Path(rpf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = []
    problems = []

    with open(rpf_path, "rb") as handle:
        root = RpfArchive(handle, 0, rpf_path.name, rpf_path.stat().st_size)
        encryption = ENC_NAMES.get(root.encryption, "unknown")

        queue = [(root, "", 0)]
        while queue:
            archive, prefix, depth = queue.pop()

            for entry in archive.files():
                if entry.name.lower().endswith(".rpf"):
                    continue
                try:
                    data = archive.read(entry)
                except NeedsKeysError:
                    skipped.append(f"{prefix}{entry.path} (encrypted entry)")
                    continue
                except RpfError as exc:
                    problems.append(f"{prefix}{entry.path}: {exc}")
                    continue

                reason = verify(entry.name, data)
                if reason:
                    problems.append(f"{prefix}{entry.path}: {reason}")
                    continue
                if entry.synthesized_header:
                    problems.append(
                        f"{prefix}{entry.path}: RSC7 header was missing and had "
                        "to be rebuilt - check this file in game"
                    )

                target = out_dir / (prefix + entry.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                written += 1
                if on_file:
                    on_file(entry.path, len(data))

            if depth < max_depth:
                for nested in archive.nested_archives():
                    try:
                        child = archive.open_nested(nested)
                    except NeedsKeysError:
                        skipped.append(f"{prefix}{nested.path} (encrypted archive)")
                        continue
                    except RpfError as exc:
                        problems.append(f"{prefix}{nested.path}: {exc}")
                        continue
                    child_prefix = f"{prefix}{nested.path[:-4]}/"
                    queue.append((child, child_prefix, depth + 1))

    return {
        "ok": written > 0,
        "encryption": encryption,
        "written": written,
        "skipped": skipped,
        "problems": problems,
    }


def inspect(rpf_path) -> dict:
    rpf_path = Path(rpf_path)
    try:
        with open(rpf_path, "rb") as handle:
            archive = RpfArchive(handle, 0, rpf_path.name, rpf_path.stat().st_size)
            return {
                "native": True,
                "encryption": ENC_NAMES.get(archive.encryption, "unknown"),
                "files": len(archive.files()),
                "nested": len(archive.nested_archives()),
            }
    except NeedsKeysError as exc:
        return {"native": False, "encryption": exc.encryption, "error": str(exc)}
    except (RpfError, OSError) as exc:
        return {"native": False, "encryption": "?", "error": str(exc)}
