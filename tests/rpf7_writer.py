import struct, zlib

RPF7 = 0x52504637
DIR_MARKER = 0x7FFFFF00
ENC_OPEN = 0x4E45504F

def _align(n, to=512):
    return (n + to - 1) // to * to

def build(files: dict) -> bytes:
    names = b""
    offsets = {}
    for name in ["", *files]:
        offsets[name] = len(names)
        names += name.encode() + b"\x00"
    names_len = _align(len(names), 16)
    names = names.ljust(names_len, b"\x00")

    entry_count = 1 + len(files)
    header_len = 16 + entry_count * 16 + names_len
    data_start = _align(header_len)

    blobs, placed, cursor = [], {}, data_start
    for name, (kind, payload) in files.items():
        if kind == "binary":
            body = zlib.compress(payload)[2:-4]
            stored, uncompressed = len(body), len(payload)
        else:
            version, sysf, gfxf = 162, 0x90000000, 0x90000000
            body = (b"RSC7" + struct.pack("<3I", version, sysf, gfxf)
                    + zlib.compress(payload)[2:-4])
            stored, uncompressed = len(body), 0
        placed[name] = (cursor // 512, stored, uncompressed)
        blobs.append((cursor, body))
        cursor = _align(cursor + len(body))

    out = bytearray()
    out += struct.pack("<4I", RPF7, entry_count, names_len, ENC_OPEN)
    out += struct.pack("<4I", offsets[""], DIR_MARKER, 1, len(files))
    for name, (kind, _payload) in files.items():
        off512, stored, uncompressed = placed[name]
        packed = offsets[name] | (stored << 16) | (off512 << 40)
        low, high = packed & 0xFFFFFFFF, (packed >> 32) & 0xFFFFFFFF
        if kind == "resource":
            high |= 0x80000000
            out += struct.pack("<4I", low, high, 0x90000000, 0x90000000)
        else:
            out += struct.pack("<4I", low, high, uncompressed, 0)
    out += names
    out = out.ljust(data_start, b"\x00")
    for at, body in blobs:
        out = out.ljust(at, b"\x00")
        out += body
    return bytes(out)
