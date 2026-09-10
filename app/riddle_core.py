# Riddle-FUVT - core logic
# Author : DanTheMan7777  |  https://github.com/DanRiddle
# License: Free-use only. See LICENSE.

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import rpf7
import riddle_archives as ra
import riddle_fixups as rfx

APP_NAME = "Riddle-FUVT"
APP_LONG_NAME = "Riddle FiveM Ultimate Vehicle Tool"
APP_VERSION = "2.0.0"
APP_AUTHOR = "DanTheMan7777"
APP_GITHUB = "https://github.com/DanRiddle"


CLASS_MAP = {
    "VC_COMPACT": "compacts", "VC_SEDAN": "sedans", "VC_SUV": "suvs",
    "VC_COUPES": "coupes", "VC_MUSCLE": "muscle", "VC_SPORT_CLASSIC": "sportsclassics",
    "VC_SPORT": "sports", "VC_SUPER": "super", "VC_MOTORCYCLE": "motorcycles",
    "VC_OFF_ROAD": "offroad", "VC_INDUSTRIAL": "industrial", "VC_UTILITY": "utility",
    "VC_VANS": "vans", "VC_CYCLES": "cycles", "VC_BOATS": "boats",
    "VC_HELICOPTER": "helicopters", "VC_PLANE": "planes", "VC_SERVICE": "service",
    "VC_EMERGENCY": "emergency", "VC_MILITARY": "military", "VC_COMMERCIAL": "commercial",
    "VC_RAIL": "trains", "VC_OPEN_WHEEL": "openwheel",
}

TYPE_MAP = {
    "VEHICLE_TYPE_CAR": "automobile", "VEHICLE_TYPE_BIKE": "bike",
    "VEHICLE_TYPE_BICYCLE": "bicycle", "VEHICLE_TYPE_BOAT": "boat",
    "VEHICLE_TYPE_HELI": "heli", "VEHICLE_TYPE_PLANE": "plane",
    "VEHICLE_TYPE_TRAIN": "train", "VEHICLE_TYPE_TRAILER": "trailer",
    "VEHICLE_TYPE_QUADBIKE": "quadbike", "VEHICLE_TYPE_SUBMARINE": "submarine",
    "VEHICLE_TYPE_SUBMARINECAR": "submarinecar",
    "VEHICLE_TYPE_AMPHIBIOUS_AUTOMOBILE": "amphibious_automobile",
    "VEHICLE_TYPE_AMPHIBIOUS_QUADBIKE": "amphibious_quadbike",
    "VEHICLE_TYPE_BLIMP": "blimp",
}

WANTED_TAGS = frozenset({
    "modelname", "gamename", "displayname", "vehiclemakename", "makename",
    "brand", "vehicleclass", "class", "type", "vehicletype", "txdname",
    "handlingid", "audionamehash", "layout", "flags",
})

SKIP_DIRS = frozenset({
    ".git", ".svn", ".idea", ".vscode", "__pycache__", "node_modules",
    "$recycle.bin", "system volume information",
})

_GXT_KEY = re.compile(r"^[A-Z0-9_]{3,}$")


_TAG_CACHE = {}


def _local(tag: str) -> str:
    cached = _TAG_CACHE.get(tag)
    if cached is None:
        cached = tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""
        _TAG_CACHE[tag] = cached
    return cached


def _text_of(el) -> str:
    if el.text and el.text.strip():
        return el.text.strip()
    for key, value in el.attrib.items():
        if _local(key) in ("value", "name", "content") and value and value.strip():
            return value.strip()
    return ""


def _direct_fields(item) -> dict:
    fields = {}
    for child in item:
        tag = _local(child.tag)
        if tag in WANTED_TAGS and tag not in fields:
            value = _text_of(child)
            if value:
                fields[tag] = value
    return fields


def pretty_name(game_name: str, model: str) -> str:
    if not game_name or _GXT_KEY.match(game_name):
        return model.replace("_", " ").title()
    return game_name.replace("_", " ").title()


def _vehicle_items(root):
    items = root.findall(".//Item")
    if not items:
        items = [el for el in root.iter() if _local(el.tag) == "item"]
    if not items:
        items = [root]
    return items


def _pretty_brand(brand: str) -> str:
    if not brand:
        return "Unknown"
    return brand if (brand.isupper() and len(brand) <= 3) else brand.title()


def parse_vehicles_meta(path: Path, default_price: int = 0) -> list:
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError, ValueError):
        return []

    results = []
    source = str(path)
    folder = str(path.parent)
    filename = path.name
    resource = _resource_name_for(path)

    for item in _vehicle_items(root):
        fields = _direct_fields(item)
        model = fields.get("modelname", "")
        if not model:
            continue

        class_key = (fields.get("vehicleclass") or fields.get("class") or "").upper()
        type_key = (fields.get("type") or fields.get("vehicletype") or "").upper()

        category = CLASS_MAP.get(class_key) or (class_key.replace("VC_", "").lower() if class_key else "other")
        vtype = TYPE_MAP.get(type_key) or (type_key.replace("VEHICLE_TYPE_", "").lower() if type_key else "automobile")

        game_name = fields.get("gamename") or fields.get("displayname") or ""
        handling_id = (fields.get("handlingid") or "").strip()
        brand = fields.get("vehiclemakename") or fields.get("makename") or fields.get("brand") or ""

        results.append({
            "model": model,
            "spawn_code": model,
            "name": pretty_name(game_name, model),
            "brand": _pretty_brand(brand),
            "price": default_price,
            "category": category,
            "type": vtype,
            "hash": model,
            "source": source,
            "folder": folder,
            "meta": filename,
            "resource": resource,
            "_gamename": game_name,
            "_handling": handling_id,
        })
    return results


_RESOURCE_CACHE = {}


def _resource_name_for(meta_path: Path) -> str:
    parent_dir = meta_path.parent
    cached = _RESOURCE_CACHE.get(parent_dir)
    if cached is not None:
        return cached

    name = parent_dir.name
    for parent in list(meta_path.parents)[:6]:
        if (parent / "fxmanifest.lua").exists() or (parent / "__resource.lua").exists():
            name = parent.name
            break
    _RESOURCE_CACHE[parent_dir] = name
    return name


def scan_folder(folder, default_price: int = 0, progress=None) -> dict:
    folder = Path(folder)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Selected path is not a valid folder.")

    meta_files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if is_vehicles_meta(name):
                meta_files.append(Path(dirpath) / name)

    total = len(meta_files)
    vehicles = []
    failed = []

    for index, meta in enumerate(meta_files, 1):
        parsed = parse_vehicles_meta(meta, default_price)
        if not parsed:
            failed.append(str(meta))
        vehicles.extend(parsed)
        if progress and (index % 10 == 0 or index == total):
            progress(index, total, meta.parent.name)

    seen = set()
    unique = []
    duplicates = 0
    for v in vehicles:
        key = v["model"].lower()
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(v)

    unique.sort(key=lambda v: v["model"].lower())

    return {
        "folder": str(folder),
        "vehicles": unique,
        "meta_files": [str(m) for m in meta_files],
        "meta_count": total,
        "duplicates_removed": duplicates,
        "unreadable": failed,
    }


def lua_quote(value) -> str:
    value = str(value or "").replace("\\", "\\\\").replace("'", "\\'")
    return "'" + value + "'"


_LUA_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LUA_KEYWORDS = frozenset({
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return",
    "then", "true", "until", "while",
})


def lua_key(name) -> str:
    name = str(name or "")
    if _LUA_IDENT.match(name) and name not in _LUA_KEYWORDS:
        return name
    return f"[{lua_quote(name)}]"


def _header() -> str:
    return (
        f"-- Generated by {APP_NAME} v{APP_VERSION}\n"
        f"-- Author: {APP_AUTHOR} | {APP_GITHUB}\n"
        "-- Free to use. Selling this tool or its output as a paid product is not permitted.\n\n"
    )




def export_qbcore(vehicles) -> str:
    rows = []
    for v in vehicles:
        rows.append(
            "    { "
            f"model = {lua_quote(v['model'])}, "
            f"name = {lua_quote(v['name'])}, "
            f"brand = {lua_quote(v['brand'])}, "
            f"price = {int(v.get('price') or 0)}, "
            f"category = {lua_quote(v['category'])}, "
            f"type = {lua_quote(v['type'])}, "
            "shop = 'pdm' },"
        )
    return (
        _header()
        + "-- Paste these inside the `local Vehicles = {` table in\n"
        + "-- qb-core/shared/vehicles.lua. Do not paste the whole file.\n\n"
        + "\n".join(rows)
        + "\n"
    )


def export_qbx(vehicles) -> str:
    rows = []
    for v in vehicles:
        rows.append(
            f"    {lua_key(v['model'])} = {{\n"
            f"        name = {lua_quote(v['name'])},\n"
            f"        brand = {lua_quote(v['brand'])},\n"
            f"        model = {lua_quote(v['model'])},\n"
            f"        price = {int(v.get('price') or 0)},\n"
            f"        category = {lua_quote(v['category'])},\n"
            f"        type = {lua_quote(v['type'])},\n"
            f"        hash = `{v['model']}`,\n"
            f"    }},"
        )
    return (
        _header()
        + "---@type table<string, Vehicle>\n"
        + "return {\n" + "\n".join(rows) + "\n}\n"
    )


def export_esx_sql(vehicles) -> str:
    rows = []
    for v in vehicles:
        name = str(v["name"]).replace("'", "''")
        model = str(v["model"]).replace("'", "''")
        category = str(v["category"]).replace("'", "''")
        rows.append(f"('{name}', '{model}', {int(v.get('price') or 0)}, '{category}')")
    return (
        _header()
        + "INSERT INTO `vehicles` (`name`, `model`, `price`, `category`) VALUES\n"
        + ",\n".join(rows)
        + ";\n"
    )


def export_spawn(vehicles) -> str:
    return "\n".join(v["model"] for v in vehicles) + "\n"








EXPORTERS = {
    "spawn": (export_spawn,   "txt",  "Spawn codes"),
    "qb":    (export_qbcore,  "lua",  "QBCore vehicles.lua"),
    "qbx":   (export_qbx,     "lua",  "Qbox vehicles.lua"),
    "esx":   (export_esx_sql, "sql",  "ESX SQL insert"),
}


def render_export(fmt: str, vehicles) -> tuple:
    if fmt not in EXPORTERS:
        raise ValueError(f"Unknown export format: {fmt}")
    fn, ext, _label = EXPORTERS[fmt]
    return fn(vehicles), ext


STREAM_EXT = frozenset({
    ".yft", ".ytd", ".ydr", ".ydd", ".ybn", ".ycd", ".ynv", ".yed",
    ".ypt", ".ytyp", ".ymap", ".ymt", ".ysc",
})
AUDIO_WAVE_EXT = frozenset({".awc"})
META_EXT = frozenset({".meta", ".xml"})

DATA_FILE_TYPES = [
    ("vehicles.meta",        "VEHICLE_METADATA_FILE"),
    ("carvariations.meta",   "VEHICLE_VARIATION_FILE"),
    ("carcols.meta",         "CARCOLS_FILE"),
    ("handling.meta",        "HANDLING_FILE"),
    ("vehiclelayouts.meta",  "VEHICLE_LAYOUTS_FILE"),
    ("contentunlocks.meta",  "CONTENT_UNLOCKING_META_FILE"),
    ("caraddoncarcols.meta", "CARCOLS_FILE"),
    ("weaponarchetypes.meta", "WEAPON_METADATA_FILE"),
    ("explosion.meta",       "EXPLOSION_INFO_FILE"),
    ("ptfxassetinfo.meta",   "PTFXASSETINFO_FILE"),
    ("vfxvehicleinfo.meta",  "VFXVEHICLEINFO_FILE"),
]
_DATA_FILE_ORDER = {name: i for i, (name, _t) in enumerate(DATA_FILE_TYPES)}
_DATA_FILE_MAP = dict(DATA_FILE_TYPES)

_DATA_FILE_PREFIXES = [
    ("vehiclelayouts", "VEHICLE_LAYOUTS_FILE"),
    ("vehicleweapons", "WEAPONINFO_FILE"),
    ("carvariations", "VEHICLE_VARIATION_FILE"),
    ("contentunlocks", "CONTENT_UNLOCKING_META_FILE"),
    ("caraddoncarcols", "CARCOLS_FILE"),
    ("vehicles", "VEHICLE_METADATA_FILE"),
    ("handling", "HANDLING_FILE"),
    ("carcols", "CARCOLS_FILE"),
]


def data_file_type(filename: str) -> str:
    name = Path(filename).name.lower()
    if name in _DATA_FILE_MAP:
        return _DATA_FILE_MAP[name] or ""
    if not name.endswith(".meta"):
        return ""
    stem = name[:-5]
    for prefix, dtype in _DATA_FILE_PREFIXES:
        if stem == prefix or stem.startswith(prefix + "_"):
            return dtype
    return ""


def is_vehicles_meta(filename) -> bool:
    return data_file_type(filename) == "VEHICLE_METADATA_FILE"

GTAUTIL_RELEASES = "https://api.github.com/repos/indilo53/gtautil/releases/latest"
GTAUTIL_PAGE = "https://github.com/indilo53/gtautil/releases/latest"
GTAUTIL_MAX_BYTES = 200 * 1024 * 1024

GTAUTIL_CANDIDATES = [
    r"C:\Program Files\gtautil\gtautil.exe",
    r"C:\Program Files (x86)\gtautil\gtautil.exe",
    r"C:\gtautil\gtautil.exe",
]


def find_gtautil(custom_path: str = "") -> str:
    if custom_path:
        p = Path(custom_path)
        if p.is_dir():
            p = p / "gtautil.exe"
        if p.exists():
            return str(p)
    found = shutil.which("gtautil") or shutil.which("gtautil.exe")
    if found:
        return found
    for candidate in GTAUTIL_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return ""


def download_gtautil(dest_dir) -> dict:
    import io
    import json as _json
    import urllib.parse
    import urllib.request
    import zipfile

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}

    try:
        request = urllib.request.Request(GTAUTIL_RELEASES, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            release = _json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"could not reach GitHub: {exc}", "page": GTAUTIL_PAGE}

    asset = next(
        (a for a in release.get("assets", []) if a.get("name", "").lower().endswith(".zip")),
        None,
    )
    if not asset:
        return {"ok": False, "error": "no zip in the latest release", "page": GTAUTIL_PAGE}

    url = asset.get("browser_download_url", "")
    host = urllib.parse.urlsplit(url).hostname or ""
    if not (host == "github.com" or host.endswith(".github.com")
            or host.endswith(".githubusercontent.com")):
        return {"ok": False, "error": f"release asset is not hosted on GitHub ({host})",
                "page": GTAUTIL_PAGE}

    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read(GTAUTIL_MAX_BYTES + 1)
        if len(payload) > GTAUTIL_MAX_BYTES:
            return {"ok": False,
                    "error": f"release zip is larger than {GTAUTIL_MAX_BYTES // 1024 // 1024} MB",
                    "page": GTAUTIL_PAGE}
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(dest_dir)
    except Exception as exc:
        return {"ok": False, "error": f"download failed: {exc}", "page": GTAUTIL_PAGE}

    found = next((p for p in dest_dir.rglob("gtautil.exe")), None)
    if not found:
        return {"ok": False, "error": "gtautil.exe not found in the release zip",
                "page": GTAUTIL_PAGE}

    return {"ok": True, "path": str(found), "version": release.get("tag_name", "")}


def _run(cmd, cwd=None, timeout=600):
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, creationflags=flags,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "gtautil timed out."
    except OSError as exc:
        return -1, str(exc)


def extract_rpf_tree(rpf_path: Path, out_dir: Path, gtautil: str, max_depth: int = 4) -> tuple:
    log = []
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = rpf7.extract_all(rpf_path, out_dir, max_depth=max_depth)
        for problem in report["problems"][:10]:
            log.append(f"warning: {problem}")
        for skip in report["skipped"][:10]:
            log.append(f"skipped: {skip}")
        if report["ok"]:
            log.insert(0, f"native reader ({report['encryption']}): "
                          f"{report['written']} file(s)")
            return True, log
        log.append("native reader found no usable files")
    except rpf7.NeedsKeysError as exc:
        log.append(f"native reader: {exc}")
    except (rpf7.RpfError, OSError) as exc:
        log.append(f"native reader failed: {exc}")

    if not gtautil:
        log.append("gtautil not configured - cannot unpack this archive")
        return False, log

    return _extract_with_gtautil(rpf_path, out_dir, gtautil, log, max_depth)


def _extract_with_gtautil(rpf_path: Path, out_dir: Path, gtautil: str,
                          log: list, max_depth: int) -> tuple:
    code, output = _run([gtautil, "extractarchive", "--input", str(rpf_path),
                         "--output", str(out_dir)])
    if code != 0:
        log.append(f"gtautil failed on {rpf_path.name}: {output.strip()[:400]}")
        return False, log
    log.append(f"gtautil unpacked {rpf_path.name}")

    for _depth in range(max_depth):
        nested = [p for p in out_dir.rglob("*.rpf") if p.is_file()]
        if not nested:
            break
        for archive in nested:
            target = archive.with_suffix("")
            target.mkdir(parents=True, exist_ok=True)
            code, output = _run([gtautil, "extractarchive", "--input", str(archive),
                                 "--output", str(target)])
            if code != 0:
                log.append(f"nested archive skipped: {archive.name} ({output.strip()[:200]})")
            try:
                archive.unlink()
            except OSError:
                pass
    return True, log


def classify_files(source_dir: Path, subfolder: str = "") -> dict:
    nest = f"{subfolder}/" if subfolder else ""
    buckets = {"stream": [], "data": [], "audioconfig": [], "sfx": [], "ignored": []}
    seen = {}
    collisions = []

    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        lower = path.name.lower()
        ext = path.suffix.lower()

        if lower in ("setup2.xml", "content.xml", "dlctext.meta") or lower.endswith(".gxt2"):
            buckets["ignored"].append((path, path.name))
            continue

        if lower.endswith(".rel"):
            bucket, target = "audioconfig", f"audioconfig/{path.name}"
        elif ext in AUDIO_WAVE_EXT:
            pack = path.parent.name or "sfx"
            bucket, target = "sfx", f"sfx/{pack}/{path.name}"
        elif ext in META_EXT:
            bucket, target = "data", f"data/{nest}{path.name}"
        elif ext in STREAM_EXT:
            bucket, target = "stream", f"stream/{nest}{path.name}"
        else:
            buckets["ignored"].append((path, path.name))
            continue

        if target in seen:
            if seen[target].read_bytes() == path.read_bytes():
                continue
            if bucket != "data":
                collisions.append(f"{target}: two different files with this name, kept the first")
                continue
            slot = 2
            while f"data/{nest}{slot}/{path.name}" in seen:
                slot += 1
            target = f"data/{nest}{slot}/{path.name}"
            collisions.append(
                f"{path.name}: this pack ships more than one, kept them all as "
                f"{nest}{slot}/{path.name}"
            )
        seen[target] = path
        buckets[bucket].append((path, target))

    buckets["collisions"] = collisions
    return buckets


def build_fxmanifest(resource_name: str, buckets: dict, extra_client: list = None) -> tuple:
    files = []
    data_files = []
    notes = []

    metas = sorted(
        buckets["data"],
        key=lambda pair: (_DATA_FILE_ORDER.get(Path(pair[1]).name.lower(), 99), pair[1].lower()),
    )
    for _src, target in metas:
        files.append(target)
        dtype = data_file_type(target)
        if dtype:
            data_files.append((dtype, target))

    for _src, target in sorted(buckets["stream"]):
        if target.lower().endswith(".ytyp"):
            data_files.append(("DLC_ITYP_REQUEST", target[:-5]))

    for src, target in sorted(buckets["audioconfig"]):
        files.append(target)
        dtype, how = rfx.rel_data_type(src)
        if dtype:
            data_files.append((dtype, rfx.rel_manifest_path(Path(target).name)))
            if how == "filename":
                notes.append(f"{Path(target).name}: audio type guessed from the filename")
        else:
            notes.append(f"{Path(target).name}: unknown audio type, no data_file written")

    wavepacks = sorted({str(Path(target).parent) for _src, target in buckets["sfx"]})
    for pack in wavepacks:
        files.append(f"{pack}/*.awc")
        data_files.append(("AUDIO_WAVEPACK", pack))

    out = [
        "fx_version 'cerulean'",
        "game 'gta5'",
        "",
        f"name '{resource_name}'",
        f"author '{APP_AUTHOR}'",
        f"description 'Add-on vehicle resource built with {APP_NAME} ({APP_GITHUB})'",
        "version '1.0.0'",
        "",
    ]
    if extra_client:
        for script in extra_client:
            out.append(f"client_script '{script}'")
        out.append("")
    if files:
        out.append("files {")
        out.extend(f"    '{f}'," for f in files)
        out.append("}")
        out.append("")
    for dtype, target in data_files:
        out.append(f"data_file '{dtype}' '{target}'")
    out.append("")
    return "\n".join(out), notes


MODEL_EXT = frozenset({".yft"})


ESCROW_MARKER = ".fxap"


def is_escrowed(folder) -> bool:
    folder = Path(folder)
    if not folder.is_dir():
        return False
    if (folder / ESCROW_MARKER).is_file():
        return True
    return any(p.name.lower() == ESCROW_MARKER for p in folder.rglob(ESCROW_MARKER))


def classify_pack(vehicles: list, files) -> tuple:
    has_meta = bool(vehicles)
    has_models = any(Path(str(f)).suffix.lower() in MODEL_EXT for f in files)

    if has_meta and has_models:
        return "vehicle", ""
    if has_meta and not has_models:
        return "asset", ("lists vehicles but ships no .yft models - it configures "
                         "vehicles that live in another resource")
    if has_models and not has_meta:
        return "asset", "ships models but no vehicles.meta - no spawn code to add"
    return "asset", "no vehicles.meta and no vehicle models"


MAX_RENAME = 10


def _content_key(path: Path) -> tuple:
    digest = hashlib.sha1()
    try:
        with open(path, "rb") as handle:
            digest.update(handle.read(1024 * 1024))
        return (path.stat().st_size, digest.hexdigest())
    except OSError:
        return (0, "")


def _rename_model(target: Path, written: list, old: str, new: str) -> list:
    old_l = old.lower()
    new_written = []
    pattern = re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE)

    def swap(match):
        text = match.group(0)
        return new.upper() if text.isupper() else new

    for src, rel in written:
        path = Path(rel)
        if rel.startswith("stream/"):
            stem = path.stem
            low = stem.lower()
            if low == old_l or low.startswith(old_l + "_") or low.startswith(old_l + "+"):
                fresh = f"{path.parent.as_posix()}/{new}{stem[len(old):]}{path.suffix}"
                try:
                    (target / rel).replace(target / fresh)
                    new_written.append((src, fresh))
                    continue
                except OSError:
                    pass
        new_written.append((src, rel))

    for _src, rel in new_written:
        if not (rel.startswith("data/") and rel.lower().endswith((".meta", ".xml"))):
            continue
        file = target / rel
        try:
            body = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        swapped, hits = pattern.subn(swap, body)
        if hits:
            file.write_text(swapped, encoding="utf-8")
    return new_written


def resolve_model_clashes(target: Path, packs: list, warnings: list) -> list:
    target = Path(target)
    claims = {}
    for pack in packs:
        for vehicle in pack["vehicles"]:
            claims.setdefault(vehicle["model"].lower(), []).append(pack)

    renames = []
    for model, owners in sorted(claims.items()):
        if len(owners) < 2:
            continue

        shippers = []
        for pack in owners:
            hit = next((rel for _s, rel in pack["written"]
                        if rel.startswith("stream/")
                        and Path(rel).suffix.lower() in MODEL_EXT
                        and Path(rel).stem.lower() == model), None)
            if hit:
                shippers.append((pack, hit))

        if len(shippers) < 2:
            warnings.append(
                f"{model}: declared by {len(owners)} resources but shipped by "
                f"{len(shippers)} - one registration wins, the rest are ignored")
            continue

        keeper_key = _content_key(target / shippers[0][1])
        suffix = 0
        for pack, rel in shippers[1:]:
            if _content_key(target / rel) == keeper_key:
                warnings.append(
                    f"{model}: {pack['sub']} ships an identical copy - "
                    "left as one vehicle rather than duplicated")
                continue
            suffix += 1
            if suffix > MAX_RENAME:
                warnings.append(
                    f"{model}: more than {MAX_RENAME} different builds - "
                    f"{pack['sub']} left under the original name")
                continue
            fresh = f"{model}_{suffix}"
            pack["written"] = _rename_model(target, pack["written"], model, fresh)
            for vehicle in pack["vehicles"]:
                if vehicle["model"].lower() == model:
                    vehicle["model"] = fresh
                    vehicle["spawn_code"] = fresh
            renames.append({"from": model, "to": fresh, "pack": pack["sub"]})
            warnings.append(
                f"{model}: {pack['sub']} ships a different build - renamed to "
                f"{fresh}. Its engine audio still binds to '{model}'.")
    return renames


def model_stems(stream: list) -> set:
    return {Path(t).stem.lower() for _s, t in stream
            if Path(t).suffix.lower() in MODEL_EXT}


def split_by_model_files(vehicles: list, stream: list = None, stems: set = None) -> tuple:
    if stems is None:
        stems = model_stems(stream or [])

    added, referenced = [], []
    for vehicle in vehicles:
        model = vehicle["model"].lower()
        if model in stems or f"{model}_hi" in stems:
            added.append(vehicle)
        else:
            referenced.append(vehicle)
    return added, referenced


def _safe_resource_name(raw: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", raw.strip()).strip("_").lower()
    return name or "addon_vehicle"


def resource_name_for(folder, prefix: str = "") -> str:
    folder = Path(folder)
    archives = [p for p in folder.glob("*.rpf") if p.is_file()]
    if not archives:
        archives = [p for p in folder.rglob("*.rpf") if p.is_file()]
    source_name = archives[0].parent.name if archives else folder.name
    return _safe_resource_name(prefix + source_name)


def build_one(folder: Path, out_root: Path, gtautil: str, prefix: str = "",
              options: dict = None, registry=None) -> dict:
    folder = Path(folder)
    options = options or {}
    log = []
    warnings = []

    archives = [p for p in folder.glob("*.rpf") if p.is_file()]
    if not archives:
        archives = [p for p in folder.rglob("*.rpf") if p.is_file()]

    resource_name = resource_name_for(folder, prefix)
    target = Path(out_root) / resource_name

    temp_dir = None
    try:
        if archives:
            temp_dir = Path(tempfile.mkdtemp(prefix="rfe_"))
            for index, archive in enumerate(archives, 1):
                slot = temp_dir / f"{index:03d}_{archive.stem}"
                ok, lines = extract_rpf_tree(archive, slot, gtautil)
                log.extend(lines)
                if not ok and len(archives) == 1:
                    return {"folder": str(folder), "resource": resource_name, "ok": False,
                            "error": "; ".join(lines) or "extraction failed", "log": log}
            source = temp_dir
        else:
            source = folder

        buckets = classify_files(source)
        warnings.extend(buckets.get("collisions", []))
        if not buckets["stream"] and not buckets["data"]:
            return {"folder": str(folder), "resource": resource_name, "ok": False,
                    "error": "No vehicle model or meta files found after extraction.", "log": log}

        target.mkdir(parents=True, exist_ok=True)
        for bucket in ("stream", "data", "audioconfig", "sfx"):
            for src, rel in buckets[bucket]:
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

        data_dir = target / "data"

        meta_paths = [target / rel for _s, rel in buckets["data"]
                      if is_vehicles_meta(rel)]
        meta_paths = [p for p in meta_paths if p.exists()]
        vehicles_meta = meta_paths[0] if meta_paths else data_dir / "vehicles.meta"
        by_meta = [(p, parse_vehicles_meta(p)) for p in meta_paths]
        listed = [v for _p, group in by_meta for v in group]
        vehicles, referenced = split_by_model_files(listed, buckets["stream"])
        if referenced and not vehicles:
            warnings.append("ships no vehicle models - looks like a wheel, livery or "
                            "tuning pack, so it adds no spawn code")
        elif referenced:
            warnings.append(
                f"{len(referenced)} meta entry(s) name a model this pack does not ship "
                f"({', '.join(v['model'] for v in referenced[:4])}"
                f"{', ...' if len(referenced) > 4 else ''}) - not counted as vehicles"
            )

        if options.get("fix_ids", True) and registry is not None:
            for folder in sorted({(target / rel).parent for _s, rel in buckets["data"]}):
                warnings.extend(rfx.fix_ids(folder, resource_name, registry))

        handling_file = data_dir / "handling.meta"
        defined = set()
        for _s, rel in buckets["data"]:
            if Path(rel).name.lower() == "handling.meta" and (target / rel).exists():
                defined |= rfx.handling_names_in(target / rel)
        missing = [v for v in vehicles if v.get("_handling")
                   and v["_handling"].upper() not in defined]

        if missing:
            if options.get("generate_handling"):
                items = []
                owner = {v["model"]: p for p, group in by_meta for v in group}
                for vehicle in missing:
                    xml, note = rfx.generate_handling(
                        vehicle["model"], vehicle["category"], vehicle.get("price") or 0
                    )
                    warnings.append(note)
                    if xml:
                        items.append(xml)
                        _repoint_handling(owner.get(vehicle["model"], vehicles_meta),
                                          vehicle["model"], vehicle["model"].upper())
                if items:
                    if handling_file.exists():
                        warnings.append("handling.meta already existed - generated entries appended")
                        items = [ET.tostring(i, encoding="unicode") for i in
                                 ET.parse(handling_file).getroot().iter("Item")] + items
                    rfx.write_handling(handling_file, items)
                    if not any(rel == "data/handling.meta" for _p, rel in buckets["data"]):
                        buckets["data"].append((handling_file, "data/handling.meta"))
            else:
                for vehicle in missing:
                    warnings.append(
                        f"{vehicle['model']}: handlingId '{vehicle['_handling']}' is not defined "
                        "in this pack - it must exist in the base game or another resource"
                    )

        client_scripts = []
        if options.get("add_labels") and vehicles:
            entries = []
            for meta_path, group in by_meta:
                got, notes = rfx.apply_labels(meta_path, group)
                warnings.extend(notes)
                entries.extend(got)
            if entries:
                (target / "labels.lua").write_text(
                    rfx.build_labels_script(entries), encoding="utf-8"
                )
                client_scripts.append("labels.lua")

        manifest, manifest_notes = build_fxmanifest(resource_name, buckets, client_scripts)
        warnings.extend(manifest_notes)
        (target / "fxmanifest.lua").write_text(manifest, encoding="utf-8")

        reread = [v for p in meta_paths for v in parse_vehicles_meta(p)]
        final_vehicles, _ref = split_by_model_files(reread, buckets["stream"])
        rows = [{"model": v["model"], "name": v["name"], "brand": v["brand"],
                 "category": v["category"]} for v in (final_vehicles or vehicles)]

        if options.get("spawn_sheet", True):
            (target / "spawncode.md").write_text(
                rfx.spawncode_sheet(resource_name, rows, options.get("spawn_command", "/car")),
                encoding="utf-8",
            )
            if not rows:
                warnings.append(
                    "no spawn code in this pack - it likely replaces a base game vehicle"
                )

        return {
            "folder": str(folder),
            "resource": resource_name,
            "path": str(target),
            "ok": True,
            "stream": len(buckets["stream"]),
            "data": len(buckets["data"]),
            "audio": len(buckets["audioconfig"]) + len(buckets["sfx"]),
            "models": [v["model"] for v in vehicles],
            "vehicle_rows": rows,
            "warnings": warnings,
            "log": log,
        }
    except Exception as exc:
        return {"folder": str(folder), "resource": resource_name, "ok": False,
                "error": f"{type(exc).__name__}: {exc}", "log": log}
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _repoint_handling(vehicles_meta: Path, model: str, new_id: str) -> None:
    if not vehicles_meta.exists():
        return
    try:
        text = vehicles_meta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    new_text, count = rfx.rewrite_field_for_model(text, model, "handlingId", new_id)
    if count:
        vehicles_meta.write_text(new_text, encoding="utf-8")


def find_buildable_folders(root) -> list:
    root = Path(root)
    if not root.is_dir():
        raise ValueError("Selected path is not a valid folder.")

    def buildable(path: Path) -> bool:
        if any(path.rglob("*.rpf")):
            return True
        has_model = any(p.suffix.lower() in (".yft", ".ydr") for p in path.rglob("*") if p.is_file())
        has_meta = any(is_vehicles_meta(p.name) for p in path.rglob("*") if p.is_file())
        return has_model and has_meta

    found = []
    if any(root.glob("*.rpf")):
        found.append(root)
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.lower() not in SKIP_DIRS and buildable(child):
            found.append(child)
    return found


def pack_folders_in(root) -> list:
    root = Path(root)
    if not root.is_dir():
        return []

    folders = sorted({p.parent for p in root.rglob("*.rpf") if p.is_file()})
    if folders:
        return folders

    models, metas = set(), set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".yft", ".ydr"):
            models.add(path.parent)
        elif is_vehicles_meta(path.name):
            metas.add(path.parent)
    if models and metas:
        return [root]
    return []


def unpack_archives(root, temp_root, progress=None) -> tuple:
    root = Path(root)
    temp_root = Path(temp_root)
    archives = ra.find_archives(root)
    notes = []
    folders = []
    stats = {"archives": len(archives), "unpacked": 0, "failed": 0, "packs": 0}

    used = set()
    origins = {}
    for index, archive in enumerate(archives, 1):
        if progress:
            progress(index - 1, len(archives), f"unpacking {archive.name}")

        stem = _safe_resource_name(archive.stem) or "archive"
        name, suffix = stem, 1
        while name in used:
            suffix += 1
            name = f"{stem}_{suffix}"
        used.add(name)

        result = ra.extract(archive, temp_root / name)
        for problem in result.get("problems", [])[:10]:
            notes.append(f"{archive.name}: {problem}")

        if not result.get("ok"):
            stats["failed"] += 1
            notes.append(f"{archive.name}: {result.get('error', 'extraction failed')}")
            continue

        stats["unpacked"] += 1
        found = pack_folders_in(result["root"])
        if not found:
            notes.append(f"{archive.name}: unpacked, but holds no vehicle pack")
            continue
        if len(found) > 1:
            notes.append(f"{archive.name}: contains {len(found)} packs, "
                         f"building each separately")
        for pack in found:
            origins[str(pack)] = f"{archive.name} ({pack.name})"
        folders.extend(found)
        stats["packs"] += len(found)

    if progress and archives:
        progress(len(archives), len(archives), "unpacked")
    stats["origins"] = origins
    return folders, notes, stats


def _duplicate_models(results) -> list:
    owners = {}
    for result in results:
        for row in result.get("vehicle_rows") or []:
            owners.setdefault(row["model"].lower(), []).append(result["resource"])
    return [f"{model}: {', '.join(res)}" for model, res in sorted(owners.items()) if len(res) > 1]


def probe_folders(root) -> dict:
    folders = find_buildable_folders(root)
    native = 0
    needs_keys = 0
    loose = 0
    details = []

    for folder in folders:
        archives = [p for p in folder.glob("*.rpf") if p.is_file()] or \
                   [p for p in folder.rglob("*.rpf") if p.is_file()]
        if not archives:
            loose += 1
            details.append({"name": folder.name, "mode": "loose files"})
            continue

        info = rpf7.inspect(archives[0])
        if info.get("native"):
            native += 1
            details.append({"name": folder.name, "mode": f"native ({info['encryption']})"})
        else:
            needs_keys += 1
            details.append({"name": folder.name, "mode": f"needs gtautil ({info['encryption']})"})

    archives = {"total": 0, "supported": 0, "unsupported": []}
    for archive in ra.find_archives(root):
        archives["total"] += 1
        info = ra.probe(archive)
        if info["supported"]:
            archives["supported"] += 1
        else:
            archives["unsupported"].append(f"{archive.name}: {info['reason']}")
    archives["unsupported"] = archives["unsupported"][:50]

    return {
        "total": len(folders),
        "native": native,
        "needs_keys": needs_keys,
        "loose": loose,
        "archives": archives,
        "backends": ra.backends(),
        "details": details[:200],
    }


def build_batch(root, out_root, gtautil: str = "", prefix: str = "",
                options: dict = None, progress=None) -> dict:
    folders = find_buildable_folders(root)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    gtautil = gtautil or find_gtautil()

    registry = rfx.IdRegistry()

    archive_temp = None
    archive_notes = []
    archive_stats = {"archives": 0, "unpacked": 0, "failed": 0, "packs": 0}
    results = []
    try:
        if ra.find_archives(root):
            archive_temp = Path(tempfile.mkdtemp(prefix="rfe_arc_"))
            extra, archive_notes, archive_stats = unpack_archives(
                root, archive_temp, progress
            )
            folders = folders + extra

        origins = archive_stats.get("origins", {})
        claimed = {}
        for index, folder in enumerate(folders, 1):
            if progress:
                progress(index - 1, len(folders), f"building {folder.name}")
            name = resource_name_for(folder, prefix)
            where = origins.get(str(folder), str(folder))
            if name in claimed:
                results.append({
                    "folder": str(folder), "resource": name, "ok": False,
                    "error": (f"'{name}' was already built from {claimed[name]} - "
                              f"refusing to overwrite it with {where}. Rename one "
                              f"of the two sources and build again."),
                    "log": [],
                })
                continue
            claimed[name] = where
            results.append(build_one(folder, out_root, gtautil, prefix, options, registry))
        if progress:
            progress(len(folders), len(folders), "done")
    finally:
        if archive_temp and archive_temp.exists():
            shutil.rmtree(archive_temp, ignore_errors=True)

    ok = [r for r in results if r.get("ok")]

    index_path = ""
    if (options or {}).get("spawn_sheet", True) and ok:
        index_path = str(out_root / "spawncodes.md")
        try:
            Path(index_path).write_text(
                rfx.spawncode_index(results,
                                    (options or {}).get("spawn_command", "/car")),
                encoding="utf-8",
            )
        except OSError:
            index_path = ""

    return {
        "spawn_index": index_path,
        "out_root": str(out_root),
        "total": len(folders),
        "built": len(ok),
        "failed": len(results) - len(ok),
        "gtautil": gtautil,
        "archives": archive_stats,
        "archive_notes": archive_notes,
        "reassigned_ids": registry.reassignments,
        "duplicate_models": _duplicate_models(ok),
        "warnings": sum(len(r.get("warnings") or []) for r in results),
        "results": results,
    }


MANIFEST_NAMES = ("fxmanifest.lua", "__resource.lua")
AUDIO_DATA_EXT = frozenset({".rel", ".nametable", ".dat", ".awc"})
_DAT_NUMBERED = re.compile(r"\.dat\d*$", re.IGNORECASE)

_RE_DATA_FILE = re.compile(r"""data_file\s+(['"])(.+?)\1\s+(['"])(.+?)\3""", re.I)
_RE_SCRIPT_ONE = re.compile(r"""\b(client_script|server_script|shared_script)\s+(['"])(.+?)\2""", re.I)
_RE_SCRIPT_MANY = re.compile(r"""\b(client_scripts|server_scripts|shared_scripts)\s*\{(.*?)\}""", re.I | re.S)
_RE_DEP_ONE = re.compile(r"""\bdependency\s+(['"])(.+?)\1""", re.I)
_RE_DEP_MANY = re.compile(r"""\bdependencies\s*\{(.*?)\}""", re.I | re.S)
_RE_FILES = re.compile(r"""\bfiles\s*\{(.*?)\}""", re.I | re.S)

JUNK_EXT = frozenset({
    ".dds", ".psd", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".gif", ".webp",
    ".txt", ".md", ".pdf", ".rtf", ".doc", ".docx", ".log",
    ".bak", ".tmp", ".old", ".orig", ".zip", ".rar", ".7z",
    ".exe", ".bat", ".cmd", ".ps1", ".url", ".lnk",
})
JUNK_NAMES = frozenset({
    "version", "desktop.ini", "thumbs.db", ".ds_store",
    ".gitignore", ".gitattributes", ".fxap", "readme", "license",
})
_RE_QUOTED = re.compile(r"""(['"])(.+?)\1""")


def find_resources(root) -> list:
    root = Path(root)
    if not root.is_dir():
        return []
    found = set()
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() in MANIFEST_NAMES:
            if not any(part.lower() in SKIP_DIRS for part in path.parts):
                found.add(path.parent)
    return sorted(found)


def _strip_lua_comments(text: str) -> str:
    text = re.sub(r"--\[\[.*?\]\]", "", text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def read_manifest(path: Path) -> dict:
    out = {"data_files": [], "scripts": [], "dependencies": [], "files": [], "ok": False}
    try:
        text = _strip_lua_comments(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return out

    out["ok"] = True
    for _q1, dtype, _q2, target in _RE_DATA_FILE.findall(text):
        out["data_files"].append((dtype, target.replace("\\", "/").lstrip("./")))
    for kind, _q, target in _RE_SCRIPT_ONE.findall(text):
        out["scripts"].append((kind, target.replace("\\", "/").lstrip("./")))
    for kind, block in _RE_SCRIPT_MANY.findall(text):
        for _q, target in _RE_QUOTED.findall(block):
            out["scripts"].append((kind.rstrip("s"), target.replace("\\", "/").lstrip("./")))
    for _q, name in _RE_DEP_ONE.findall(text):
        out["dependencies"].append(name)
    for block in _RE_DEP_MANY.findall(text):
        out["dependencies"].extend(name for _q, name in _RE_QUOTED.findall(block))
    for block in _RE_FILES.findall(text):
        out["files"].extend(name.replace("\\", "/").lstrip("./")
                            for _q, name in _RE_QUOTED.findall(block))
    return out


def scan_resource(path, skip_roots=()) -> dict:
    path = Path(path)
    manifest_file = next(
        (path / n for n in MANIFEST_NAMES if (path / n).is_file()), None
    )
    manifest = read_manifest(manifest_file) if manifest_file else {
        "data_files": [], "scripts": [], "dependencies": [], "ok": False}

    skip = [Path(s) for s in skip_roots]
    files = []
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        if item.name.lower() in MANIFEST_NAMES and item.parent == path:
            continue
        if any(part.lower() in SKIP_DIRS for part in item.parts):
            continue
        if any(item.is_relative_to(s) for s in skip):
            continue
        files.append(item)

    vehicles = []
    for item in files:
        if is_vehicles_meta(item.name):
            vehicles.extend(parse_vehicles_meta(item))

    return {
        "path": str(path),
        "name": path.name,
        "manifest": manifest,
        "manifest_file": str(manifest_file) if manifest_file else "",
        "files": files,
        "vehicles": vehicles,
    }


def is_junk_file(item: Path) -> bool:
    name = item.name.lower()
    return (item.suffix.lower() in JUNK_EXT
            or name in JUNK_NAMES
            or Path(name).stem in JUNK_NAMES)


def declared_paths(root: Path, manifest: dict) -> set:
    kept = set()
    listed = list(manifest.get("files") or [])
    listed += [p for _t, p in manifest.get("data_files") or []]
    listed += [p for _k, p in manifest.get("scripts") or []]
    for entry in listed:
        if any(ch in entry for ch in "*?["):
            try:
                kept.update(p.resolve() for p in root.glob(entry))
            except (ValueError, OSError):
                pass
        else:
            kept.add((root / entry).resolve())
    return kept


def _resource_target(item: Path, root: Path, sub: str) -> str:
    rel = item.relative_to(root).as_posix()
    parts = rel.split("/")
    lower = [p.lower() for p in parts]
    ext = item.suffix.lower()
    name = item.name

    if "stream" in lower:
        tail = "/".join(parts[lower.index("stream") + 1:])
        return f"stream/{sub}/{tail}"
    if ext == ".awc" or "sfx" in lower:
        pack = item.parent.name or sub
        return f"sfx/{pack}/{name}"
    if ext in AUDIO_DATA_EXT or _DAT_NUMBERED.search(ext) or "audioconfig" in lower:
        return f"audioconfig/{name}"
    if ext in META_EXT:
        tail = "/".join(parts[lower.index("data") + 1:]) if "data" in lower else name
        return f"data/{sub}/{tail}"
    if ext in STREAM_EXT:
        return f"stream/{sub}/{name}"
    return f"scripts/{sub}/{rel}"


def _unique_sub(name: str, taken: set) -> str:
    base = _safe_resource_name(name)
    candidate = base
    counter = 2
    while candidate in taken:
        candidate = f"{base}_{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def merge_resources(root, out_root, resource_name: str = "",
                    options: dict = None, progress=None) -> dict:
    options = options or {}
    root = Path(root)
    out_root = Path(out_root)
    registry = rfx.IdRegistry()

    roots = find_resources(root)
    if not roots:
        return {"ok": False, "error": "No built resources found in that folder.",
                "out_root": str(out_root)}

    warnings = []
    packs = []
    left_alone = []
    taken = set()
    skipped_files = 0

    for index, res_root in enumerate(roots, 1):
        if progress:
            progress(index - 1, len(roots), f"reading {res_root.name}")
        nested = [r for r in roots if r != res_root and r.is_relative_to(res_root)]
        info = scan_resource(res_root, nested)
        if not info["files"]:
            left_alone.append({"name": res_root.name, "path": str(res_root),
                               "reason": "empty resource", "vehicles": 0})
            continue

        if is_escrowed(res_root):
            left_alone.append({"name": res_root.name, "path": str(res_root),
                               "reason": ("protected by Cfx asset escrow (.fxap) - it can only run under its own resource name, so merging it would break it"),
                               "vehicles": len(info["vehicles"]), "escrow": True})
            continue

        kind, reason = classify_pack(info["vehicles"], info["files"])
        if kind == "asset":
            left_alone.append({"name": res_root.name, "path": str(res_root),
                               "reason": reason, "vehicles": 0})
            continue

        if not info["manifest"]["ok"]:
            warnings.append(f"{res_root.name}: manifest could not be read - "
                            "falling back to the files on disk")

        sub = _unique_sub(res_root.name, taken)
        keep_anyway = declared_paths(res_root, info["manifest"])
        usable, junk = [], 0
        for f in info["files"]:
            if is_junk_file(f) and f.resolve() not in keep_anyway:
                junk += 1
                continue
            usable.append(f)
        if junk:
            skipped_files += junk
            warnings.append(f"{sub}: skipped {junk} non-game file(s) "
                            "(templates, readmes, sources)")
        pairs = [(f, _resource_target(f, res_root, sub)) for f in usable]
        vehicles, referenced = split_by_model_files(
            info["vehicles"], [(s, t) for s, t in pairs if t.startswith("stream/")]
        )
        if not vehicles:
            left_alone.append({
                "name": res_root.name, "path": str(res_root), "vehicles": 0,
                "reason": "its meta entries name models it does not ship"})
            continue
        if referenced:
            warnings.append(
                f"{sub}: {len(referenced)} meta entry(s) name a model this resource "
                f"does not ship - not counted as vehicles")

        packs.append({
            "sub": sub, "root": res_root, "info": info,
            "pairs": pairs, "vehicles": vehicles, "referenced": referenced,
        })

    if not packs:
        return {"ok": False,
                "error": ("No vehicle resources found. Everything in that folder "
                          "looks like wheels, EUP, an MLO, a map or audio."),
                "left_alone": left_alone, "warnings": warnings,
                "out_root": str(out_root)}

    everything = set()
    for pack in packs:
        everything |= model_stems([(s, t) for s, t in pack["pairs"]
                                   if t.startswith("stream/")])
    for pack in packs:
        pack["vehicles"], pack["referenced"] = split_by_model_files(
            pack["info"]["vehicles"], stems=everything)

    name = _safe_resource_name(resource_name or f"{root.name}_merged")
    target = out_root / name
    target.mkdir(parents=True, exist_ok=True)

    claimed = {}
    written = {}
    total = sum(len(p["pairs"]) for p in packs)
    done = 0
    for pack in packs:
        keep = []
        for src, rel in pack["pairs"]:
            if rel.startswith(("audioconfig/", "sfx/")):
                if rel in claimed:
                    if claimed[rel] != pack["sub"]:
                        warnings.append(
                            f"{pack['sub']}: audio file '{rel}' is already provided "
                            f"by {claimed[rel]} - kept the first")
                    done += 1
                    continue
                claimed[rel] = pack["sub"]
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            keep.append((src, rel))
            done += 1
            if progress and done % 50 == 0:
                progress(done, total, f"copying {Path(rel).name}")
        pack["written"] = keep

    if progress:
        progress(total, total, "resolving duplicate spawn codes")
    renames = resolve_model_clashes(target, packs, warnings)

    written = {p["sub"]: {Path(s).resolve(): r for s, r in p["written"]} for p in packs}

    if progress:
        progress(total, total, "writing manifest")

    files, data_files, scripts, deps = [], [], [], []
    for pack in packs:
        sub, res_root = pack["sub"], pack["root"]
        declared = {}
        for dtype, decl in pack["info"]["manifest"]["data_files"]:
            if any(ch in decl for ch in "*?["):
                try:
                    sources = sorted(res_root.glob(decl))
                except (ValueError, OSError):
                    sources = []
                if not sources:
                    warnings.append(f"{sub}: '{decl}' matched no files")
            else:
                sources = [res_root / decl]
            for source in sources:
                rel = written[sub].get(source.resolve())
                if rel:
                    declared[rel] = dtype

        for _src, rel in pack["written"]:
            base = Path(rel).name.lower()
            if rel.startswith("stream/"):
                if rel.lower().endswith(".ytyp"):
                    data_files.append(("DLC_ITYP_REQUEST", rel[:-5]))
                continue
            if rel.startswith("sfx/"):
                continue
            files.append(rel)
            if rel in declared:
                data_files.append((declared[rel], rel))
            elif rel.startswith("data/"):
                dtype = data_file_type(base)
                if dtype:
                    data_files.append((dtype, rel))
            elif rel.startswith("audioconfig/") and rel.lower().endswith(".rel"):
                dtype, _how = rfx.rel_data_type(Path(_src))
                if dtype:
                    data_files.append((dtype, rfx.rel_manifest_path(Path(rel).name)))

        for kind, script in pack["info"]["manifest"]["scripts"]:
            source = (res_root / script)
            rel = written[sub].get(source.resolve())
            if rel:
                scripts.append((kind, rel))
            elif "*" not in script:
                warnings.append(f"{sub}: {kind} '{script}' was declared but not found")
        deps.extend(pack["info"]["manifest"]["dependencies"])

    for pack in packs:
        for _src, rel in pack["written"]:
            if rel.startswith("sfx/"):
                folder = str(Path(rel).parent)
                if ("AUDIO_WAVEPACK", folder) not in data_files:
                    data_files.append(("AUDIO_WAVEPACK", folder))
                    files.append(f"{folder}/*.awc")

    out = [
        "fx_version 'cerulean'", "game 'gta5'", "",
        f"name '{name}'", f"author '{APP_AUTHOR}'",
        f"description 'Merged vehicle resource built with {APP_NAME} ({APP_GITHUB})'",
        "version '1.0.0'", "",
    ]
    for dep in sorted(set(deps)):
        out.append(f"dependency '{dep}'")
    if deps:
        out.append("")
    for kind, script in scripts:
        out.append(f"{kind} '{script}'")
    if scripts:
        out.append("")
    if files:
        out.append("files {")
        out.extend(f"    '{f}'," for f in sorted(set(files)))
        out.append("}")
        out.append("")
    seen_df = set()
    for dtype, rel in data_files:
        if (dtype, rel) in seen_df:
            continue
        seen_df.add((dtype, rel))
        out.append(f"data_file '{dtype}' '{rel}'")
    out.append("")
    (target / "fxmanifest.lua").write_text("\n".join(out), encoding="utf-8")

    if options.get("fix_ids", True):
        for pack in packs:
            for folder in sorted({(target / rel).parent
                                  for _s, rel in pack["written"] if rel.startswith("data/")}):
                warnings.extend(f"{pack['sub']}: {n}"
                                for n in rfx.fix_ids(folder, pack["sub"], registry))

    rows, seen_models = [], set()
    for pack in packs:
        for v in pack["vehicles"]:
            key = v["model"].lower()
            if key in seen_models:
                continue
            seen_models.add(key)
            rows.append({"model": v["model"], "name": v["name"],
                         "brand": v["brand"], "category": v["category"]})

    sheet = ""
    if options.get("spawn_sheet", True):
        sheet = str(target / "spawncode.md")
        (target / "spawncode.md").write_text(
            rfx.spawncode_sheet(name, rows, options.get("spawn_command", "/car")),
            encoding="utf-8")

    return {
        "ok": True, "mode": "resources",
        "resource": name, "path": str(target), "out_root": str(out_root),
        "packs": len(packs),
        "sources": [{"sub": p["sub"], "origin": str(p["root"]),
                     "vehicles": len(p["vehicles"]),
                     "referenced": len(p["referenced"])} for p in packs],
        "vehicles": len(rows), "vehicle_rows": rows,
        "left_alone": left_alone, "renames": renames,
        "skipped_files": skipped_files,
        "escrowed": sum(1 for a in left_alone if a.get("escrow")),
        "asset_packs": len(left_alone),
        "referenced": sum(len(p["referenced"]) for p in packs),
        "stream": sum(1 for p in packs for _s, r in p["written"] if r.startswith("stream/")),
        "data": sum(1 for p in packs for _s, r in p["written"] if r.startswith("data/")),
        "audio": sum(1 for p in packs for _s, r in p["written"]
                     if r.startswith(("audioconfig/", "sfx/"))),
        "scripts": len(scripts),
        "spawn_sheet": sheet, "gtautil": "",
        "archives": {"archives": 0, "unpacked": 0, "failed": 0, "packs": 0},
        "archive_notes": [], "reassigned_ids": registry.reassignments,
        "warnings": warnings,
    }


def merge_batch(root, out_root, gtautil: str = "", resource_name: str = "",
                options: dict = None, progress=None) -> dict:
    options = options or {}
    root = Path(root)
    out_root = Path(out_root)
    gtautil = gtautil or find_gtautil()
    registry = rfx.IdRegistry()

    if not options.get("force_packs") and find_resources(root):
        return merge_resources(root, out_root, resource_name, options, progress)

    folders = find_buildable_folders(root)
    archive_temp = None
    archive_notes = []
    archive_stats = {"archives": 0, "unpacked": 0, "failed": 0, "packs": 0}

    packs = []
    left_alone = []
    warnings = []
    temp_dirs = []

    try:
        if ra.find_archives(root):
            archive_temp = Path(tempfile.mkdtemp(prefix="rfe_arc_"))
            extra, archive_notes, archive_stats = unpack_archives(root, archive_temp, progress)
            folders = folders + extra

        if not folders:
            return {"ok": False, "error": "No vehicle packs found in that folder.",
                    "out_root": str(out_root)}

        origins = archive_stats.get("origins", {})
        taken = set()

        units = []
        for folder in folders:
            rpfs = sorted(p for p in folder.rglob("*.rpf") if p.is_file())
            if rpfs:
                units.extend((rpf.parent.name or folder.name, folder, rpf) for rpf in rpfs)
            else:
                units.append((folder.name, folder, None))

        for index, (label, folder, rpf) in enumerate(units, 1):
            if progress:
                progress(index - 1, len(units), f"reading {label}")

            sub = _unique_sub(label, taken)
            source = folder
            if rpf is not None:
                temp_dir = Path(tempfile.mkdtemp(prefix="rfe_m_"))
                temp_dirs.append(temp_dir)
                ok, lines = extract_rpf_tree(rpf, temp_dir, gtautil)
                if not ok:
                    warnings.append(f"{sub}: {'; '.join(lines) or 'extraction failed'}")
                    continue
                source = temp_dir

            buckets = classify_files(source, sub)
            warnings.extend(f"{sub}: {c}" for c in buckets.get("collisions", []))
            if not buckets["stream"] and not buckets["data"]:
                warnings.append(f"{sub}: no model or meta files found, skipped")
                continue

            listed = []
            for src, target in buckets["data"]:
                if is_vehicles_meta(target):
                    listed.extend(parse_vehicles_meta(src))

            vehicles, referenced = split_by_model_files(listed, buckets["stream"])
            if is_escrowed(folder):
                left_alone.append({"name": sub, "path": str(rpf or folder),
                                   "vehicles": len(listed), "escrow": True,
                                   "reason": ("protected by Cfx asset escrow (.fxap) - it can only run under its own resource name, so merging it would break it")})
                continue

            kind, reason = classify_pack(
                listed, [t for _s, t in buckets["stream"]])
            if kind == "asset" or not vehicles:
                left_alone.append({
                    "name": sub, "path": str(rpf or folder), "vehicles": 0,
                    "reason": reason or "its meta entries name models it does not ship"})
                continue
            if referenced:
                warnings.append(
                    f"{sub}: {len(referenced)} entry(s) name a model this pack does not "
                    f"ship ({', '.join(v['model'] for v in referenced[:4])}"
                    f"{', ...' if len(referenced) > 4 else ''}) - not counted as vehicles"
                )

            packs.append({
                "sub": sub,
                "folder": str(folder),
                "origin": origins.get(str(folder), str(rpf or folder)),
                "buckets": buckets,
                "vehicles": vehicles,
                "referenced": referenced,
            })

        if not packs:
            return {"ok": False,
                    "error": ("No vehicle packs found. Everything in that folder looks "
                              "like wheels, EUP, an MLO, a map or audio."),
                    "left_alone": left_alone, "warnings": warnings,
                    "out_root": str(out_root)}

        everything = set()
        for pack in packs:
            everything |= model_stems(pack["buckets"]["stream"])
        for pack in packs:
            listed = []
            for src, target in pack["buckets"]["data"]:
                if is_vehicles_meta(target):
                    listed.extend(parse_vehicles_meta(src))
            pack["vehicles"], pack["referenced"] = split_by_model_files(
                listed, stems=everything)

        name = _safe_resource_name(resource_name or f"{root.name}_merged")
        target = out_root / name
        target.mkdir(parents=True, exist_ok=True)

        merged = {"stream": [], "data": [], "audioconfig": [], "sfx": [], "ignored": []}
        shared_claimed = {}

        total_files = sum(
            len(p["buckets"][b]) for p in packs
            for b in ("stream", "data", "audioconfig", "sfx")
        )
        done = 0
        for pack in packs:
            for bucket in ("stream", "data", "audioconfig", "sfx"):
                for src, rel in pack["buckets"][bucket]:
                    if bucket in ("audioconfig", "sfx"):
                        if rel in shared_claimed:
                            warnings.append(
                                f"{pack['sub']}: audio file '{rel}' is already provided "
                                f"by {shared_claimed[rel]} - kept the first"
                            )
                            done += 1
                            continue
                        shared_claimed[rel] = pack["sub"]
                    dest = target / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    merged[bucket].append((dest, rel))
                    pack.setdefault("written", []).append((dest, rel))
                    done += 1
                    if progress and done % 25 == 0:
                        progress(done, total_files, f"copying {Path(rel).name}")

        if progress:
            progress(total_files, total_files, "resolving duplicate spawn codes")
        for pack in packs:
            pack.setdefault("written", [])
        renames = resolve_model_clashes(target, packs, warnings)
        if renames:
            merged = {k: [] for k in merged}
            for pack in packs:
                for src, rel in pack["written"]:
                    bucket = ("stream" if rel.startswith("stream/") else
                              "data" if rel.startswith("data/") else
                              "sfx" if rel.startswith("sfx/") else
                              "audioconfig" if rel.startswith("audioconfig/") else "ignored")
                    merged[bucket].append((src, rel))

        if progress:
            progress(total_files, total_files, "writing manifest")

        client_scripts = []
        label_entries = []
        for pack in packs:
            metas = [target / rel for _s, rel in pack["buckets"]["data"]
                     if is_vehicles_meta(rel)]
            data_dirs = sorted({(target / rel).parent
                                for _s, rel in pack["buckets"]["data"]})

            if options.get("fix_ids", True):
                for data_dir in data_dirs:
                    warnings.extend(f"{pack['sub']}: {n}"
                                    for n in rfx.fix_ids(data_dir, pack["sub"], registry))

            if options.get("add_labels") and pack["vehicles"]:
                for vehicles_meta in metas:
                    if not vehicles_meta.exists():
                        continue
                    entries, notes = rfx.apply_labels(vehicles_meta, pack["vehicles"])
                    warnings.extend(f"{pack['sub']}: {n}" for n in notes)
                    label_entries.extend(entries)

        if label_entries:
            (target / "labels.lua").write_text(
                rfx.build_labels_script(label_entries), encoding="utf-8"
            )
            client_scripts.append("labels.lua")

        manifest, notes = build_fxmanifest(name, merged, client_scripts)
        warnings.extend(notes)
        (target / "fxmanifest.lua").write_text(manifest, encoding="utf-8")

        rows = []
        seen_models = set()
        for pack in packs:
            final = []
            for _s, rel in pack["buckets"]["data"]:
                if is_vehicles_meta(rel) and (target / rel).exists():
                    final.extend(parse_vehicles_meta(target / rel))
            final, _ref = split_by_model_files(final, stems=everything)
            for v in final or pack["vehicles"]:
                key = v["model"].lower()
                if key in seen_models:
                    continue
                seen_models.add(key)
                rows.append({"model": v["model"], "name": v["name"],
                             "brand": v["brand"], "category": v["category"]})

        sheet = ""
        if options.get("spawn_sheet", True):
            sheet = str(target / "spawncode.md")
            (target / "spawncode.md").write_text(
                rfx.spawncode_sheet(name, rows, options.get("spawn_command", "/car")),
                encoding="utf-8",
            )

        return {
            "ok": True,
            "resource": name,
            "path": str(target),
            "out_root": str(out_root),
            "packs": len(packs),
            "sources": [{"sub": p["sub"], "origin": p["origin"],
                         "vehicles": len(p["vehicles"]),
                         "referenced": len(p.get("referenced") or [])} for p in packs],
            "vehicles": len(rows),
            "left_alone": left_alone, "renames": renames,
            "escrowed": sum(1 for a in left_alone if a.get("escrow")),
            "asset_packs": len(left_alone),
            "referenced": sum(len(p.get("referenced") or []) for p in packs),
            "vehicle_rows": rows,
            "stream": len(merged["stream"]),
            "data": len(merged["data"]),
            "audio": len(merged["audioconfig"]) + len(merged["sfx"]),
            "spawn_sheet": sheet,
            "gtautil": gtautil,
            "archives": archive_stats,
            "archive_notes": archive_notes,
            "reassigned_ids": registry.reassignments,
            "warnings": warnings,
        }
    finally:
        if archive_temp and archive_temp.exists():
            shutil.rmtree(archive_temp, ignore_errors=True)
        for temp_dir in temp_dirs:
            shutil.rmtree(temp_dir, ignore_errors=True)
