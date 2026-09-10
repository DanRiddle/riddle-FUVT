# Riddle-FUVT - conversion fixups
# Author : DanTheMan7777  |  https://github.com/DanRiddle
# License: Free-use only. See LICENSE.

from __future__ import annotations

import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"


REL_VERSION_TYPES = {
    151: "AUDIO_GAMEDATA",
    54: "AUDIO_SOUNDDATA",
    10: "AUDIO_SYNTHDATA",
    4: "AUDIO_SPEECHDATA",
    22: "AUDIO_DYNAMIXDATA",
}

REL_NAME_TYPES = [
    (".dat151.rel", "AUDIO_GAMEDATA"),
    (".dat54.rel", "AUDIO_SOUNDDATA"),
    (".dat10.rel", "AUDIO_SYNTHDATA"),
    (".dat4.rel", "AUDIO_SPEECHDATA"),
    ("_game.dat.rel", "AUDIO_GAMEDATA"),
    ("_sounds.dat.rel", "AUDIO_SOUNDDATA"),
    ("_amp.dat.rel", "AUDIO_SYNTHDATA"),
]

_DAT_SUFFIX = re.compile(r"\.dat\d*\.rel$", re.IGNORECASE)


def rel_data_type(path: Path) -> tuple:
    try:
        with open(path, "rb") as handle:
            version = struct.unpack("<I", handle.read(4))[0]
        if version in REL_VERSION_TYPES:
            return REL_VERSION_TYPES[version], f"header v{version}"
    except (OSError, struct.error):
        pass

    lower = path.name.lower()
    for suffix, dtype in REL_NAME_TYPES:
        if lower.endswith(suffix):
            return dtype, "filename"
    return "", "unknown"


def rel_manifest_path(filename: str) -> str:
    return "audioconfig/" + _DAT_SUFFIX.sub(".dat", filename)


class IdRegistry:

    def __init__(self, siren_start: int = 2000):
        self.sirens = {}
        self._used_sirens = set()
        self._next_siren = siren_start
        self.reassignments = []

    def _take_siren(self) -> int:
        cursor = self._next_siren
        while cursor in self._used_sirens:
            cursor += 1
        self._used_sirens.add(cursor)
        self._next_siren = cursor + 1
        return cursor

    def siren_id(self, resource: str, old: int) -> int:
        key = (resource, old)
        if key in self.sirens:
            return self.sirens[key]
        if old not in self._used_sirens:
            self._used_sirens.add(old)
            self.sirens[key] = old
            return old
        new = self._take_siren()
        self.sirens[key] = new
        self.reassignments.append(f"{resource}: siren {old} -> {new}")
        return new


def _rewrite_ids(text: str, pattern: str, mapper) -> tuple:
    changes = []

    def sub(match):
        old = int(match.group("id"))
        new = mapper(old)
        if new == old:
            return match.group(0)
        changes.append((old, new))
        return match.group(0).replace(match.group("id"), str(new), 1)

    return re.sub(pattern, sub, text), changes


SIREN_IN_CARCOLS = r'<id\s+value="(?P<id>\d+)"\s*/>'
SIREN_IN_VARIATIONS = r'<sirenSettings\s+value="(?P<id>\d+)"\s*/>'


def fix_ids(data_dir: Path, resource: str, registry: IdRegistry) -> list:
    notes = []
    carcols = data_dir / "carcols.meta"
    variations = data_dir / "carvariations.meta"

    if not carcols.exists():
        return notes

    try:
        carcols_text = carcols.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return notes

    sirens_block = re.search(r"<Sirens>.*?</Sirens>", carcols_text, re.S)
    if not sirens_block:
        return notes

    mapping = {}

    def mapper(old):
        new = registry.siren_id(resource, old)
        mapping[old] = new
        return new

    block_text, changes = _rewrite_ids(sirens_block.group(0), SIREN_IN_CARCOLS, mapper)
    if not changes:
        return notes

    carcols_text = carcols_text[:sirens_block.start()] + block_text + carcols_text[sirens_block.end():]
    carcols.write_text(carcols_text, encoding="utf-8")

    if variations.exists():
        try:
            var_text = variations.read_text(encoding="utf-8", errors="replace")
            var_text, _ = _rewrite_ids(
                var_text, SIREN_IN_VARIATIONS, lambda old: mapping.get(old, old)
            )
            variations.write_text(var_text, encoding="utf-8")
        except OSError:
            pass

    for old, new in changes:
        notes.append(f"siren id {old} was already taken, moved to {new}")
    return notes


_templates_cache = None


def load_handling_templates() -> dict:
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache

    path = DATA_DIR / "handling_templates.xml"
    templates = {}
    try:
        root = ET.parse(path).getroot()
        for item in root.iter("Item"):
            klass = item.get("class")
            if klass:
                templates[klass.lower()] = item
    except (ET.ParseError, OSError):
        pass
    _templates_cache = templates
    return templates


NO_GENERATE_CLASSES = frozenset({
    "boats", "planes", "helicopters", "cycles", "trains", "openwheel",
})

CLASS_FALLBACK = {
    "coupes": "sports",
    "service": "vans",
    "commercial": "vans",
    "industrial": "vans",
    "utility": "vans",
    "military": "offroad",
    "quadbike": "offroad",
}


def handling_names_in(path: Path) -> set:
    names = set()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return names
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() == "handlingname":
            if element.text and element.text.strip():
                names.add(element.text.strip().upper())
    return names


def generate_handling(model: str, vehicle_class: str, price: int = 0) -> tuple:
    klass = (vehicle_class or "").lower()
    klass = CLASS_FALLBACK.get(klass, klass)

    if klass in NO_GENERATE_CLASSES:
        return "", (f"{model}: class '{vehicle_class}' needs SubHandlingData that "
                    "cannot be guessed - add handling by hand")

    templates = load_handling_templates()
    template = templates.get(klass) or templates.get("sedans")
    if template is None:
        return "", f"{model}: no handling template available"

    clone = ET.fromstring(ET.tostring(template))
    clone.attrib.pop("class", None)

    for child in clone:
        tag = child.tag.lower()
        if tag == "handlingname":
            child.text = model.upper()
        elif tag == "nmonetaryvalue":
            child.set("value", str(int(price or 0)))

    xml = ET.tostring(clone, encoding="unicode")
    used = klass if klass in templates else "sedans"
    return xml, f"{model}: generated handling from the '{used}' template - tune before shipping"


def write_handling(path: Path, items: list) -> None:
    body = "\n".join("    " + item for item in items)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Generated by Riddle-FUVT. These are template values,\n"
        "     not the original author's tuning. Adjust before going live. -->\n"
        "<CHandlingDataMgr>\n  <HandlingData>\n"
        + body
        + "\n  </HandlingData>\n</CHandlingDataMgr>\n",
        encoding="utf-8",
    )


_GXT_KEY = re.compile(r"^[A-Z0-9_]{2,}$")

_ITEM_TAG = re.compile(r"<(/?)Item\b[^>]*?(/?)>", re.I)


def _enclosing_item(text: str, pos: int):
    open_stack = []
    for match in _ITEM_TAG.finditer(text):
        closing, self_closing = match.group(1), match.group(2)
        if closing:
            if open_stack:
                start = open_stack.pop()
                if start <= pos < match.end():
                    return start, match.end()
        elif not self_closing:
            open_stack.append(match.start())
    return None


def rewrite_field_for_model(text: str, model: str, tag: str, value: str) -> tuple:
    model_re = re.compile(
        r"<modelName>\s*" + re.escape(model) + r"\s*</modelName>", re.I
    )
    field_re = re.compile(r"(<" + tag + r"\b[^>]*>)([^<]*)(</" + tag + r">)", re.I)

    for found in model_re.finditer(text):
        bounds = _enclosing_item(text, found.start())
        if bounds is None:
            continue
        start, end = bounds
        block, count = field_re.subn(
            lambda m: m.group(1) + value + m.group(3), text[start:end], count=1
        )
        if count:
            return text[:start] + block + text[end:], 1
    return text, 0


def needs_label(game_name: str) -> bool:
    return bool(game_name) and bool(_GXT_KEY.match(game_name.strip()))


def label_key(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", model).upper()[:20] or "VEHICLE"


def build_labels_script(entries: list) -> str:
    lines = [
        "-- Generated by Riddle-FUVT",
        "-- Author: DanTheMan7777 | https://github.com/DanRiddle",
        "-- Gives the vehicle a real display name instead of a raw text key.",
        "",
        "CreateThread(function()",
    ]
    for key, name in entries:
        safe = str(name).replace("'", "\\'")
        lines.append(f"    AddTextEntry('{key}', '{safe}')")
    lines.append("end)")
    lines.append("")
    return "\n".join(lines)


def apply_labels(vehicles_meta: Path, vehicles: list) -> tuple:
    entries = []
    notes = []
    try:
        text = vehicles_meta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries, notes

    changed = False
    for vehicle in vehicles:
        model = vehicle["model"]
        current = vehicle.get("_gamename") or ""
        if not needs_label(current):
            continue

        key = label_key(model)
        if key == current.upper():
            continue

        new_text, count = rewrite_field_for_model(text, model, "gameName", key)
        if count:
            text = new_text
            changed = True
            entries.append((key, vehicle["name"]))
            notes.append(f"{model}: gameName '{current}' was a text key, now '{key}'")

    if changed:
        vehicles_meta.write_text(text, encoding="utf-8")
    return entries, notes


CREDIT = "Built with Riddle-FUVT by DanTheMan7777 - https://github.com/DanRiddle"


def _fence(lines) -> list:
    return ["```"] + list(lines) + ["```", ""]


def spawncode_sheet(resource: str, vehicles: list, command: str = "/car") -> str:
    command = (command or "/car").strip()
    out = [
        f"# {resource}",
        "",
        CREDIT,
        "",
    ]

    if not vehicles:
        out += [
            "No spawn code found in this resource.",
            "",
            "That usually means the pack replaces a base game vehicle instead of",
            "adding a new one, so it spawns under the original code.",
            "",
        ]
        return "\n".join(out)

    out += [
        f"## {len(vehicles)} vehicle" + ("s" if len(vehicles) != 1 else ""),
        "",
        "| Vehicle | Brand | Class | Spawn code | Command |",
        "| --- | --- | --- | --- | --- |",
    ]
    for v in vehicles:
        out.append(
            f"| {v['name']} | {v['brand']} | {v['category']} | "
            f"`{v['model']}` | `{command} {v['model']}` |"
        )
    out.append("")

    out.append("## Commands")
    out.append("")
    out += _fence(f"{command} {v['model']}" for v in vehicles)

    out.append("## Spawn codes only")
    out.append("")
    out += _fence(v["model"] for v in vehicles)

    out.append("## server.cfg")
    out.append("")
    out += _fence([f"ensure {resource}"])

    return "\n".join(out)


def spawncode_index(results: list, command: str = "/car") -> str:
    command = (command or "/car").strip()
    built = [r for r in results if r.get("ok")]
    total = sum(len(r.get("vehicle_rows") or []) for r in built)

    out = [
        "# Spawn codes",
        "",
        CREDIT,
        "",
        f"{len(built)} resource" + ("s" if len(built) != 1 else "")
        + f", {total} vehicle" + ("s" if total != 1 else "") + ".",
        "",
        "| Vehicle | Spawn code | Command | Resource |",
        "| --- | --- | --- | --- |",
    ]

    for result in built:
        for v in result.get("vehicle_rows") or []:
            out.append(
                f"| {v['name']} | `{v['model']}` | `{command} {v['model']}` | "
                f"{result['resource']} |"
            )
    out.append("")

    out.append("## All commands")
    out.append("")
    out += _fence(
        f"{command} {v['model']}"
        for r in built for v in (r.get("vehicle_rows") or [])
    )

    out.append("## server.cfg")
    out.append("")
    out += _fence(f"ensure {r['resource']}" for r in built)

    owners = {}
    for result in built:
        for v in result.get("vehicle_rows") or []:
            owners.setdefault(v["model"].lower(), []).append(result["resource"])
    clashes = {m: rs for m, rs in owners.items() if len(rs) > 1}
    if clashes:
        out.append("## Duplicate spawn codes")
        out.append("")
        out.append("More than one resource registers these. Only one will load —")
        out.append("rename the model in the others or drop the duplicates.")
        out.append("")
        out.append("| Spawn code | Claimed by |")
        out.append("| --- | --- |")
        for model, resources in sorted(clashes.items()):
            out.append(f"| `{model}` | {', '.join(resources)} |")
        out.append("")

    empty = [r for r in built if not (r.get("vehicle_rows") or [])]
    if empty:
        out.append("## No spawn code found")
        out.append("")
        out.append("These built fine but add no new spawn code, which normally means")
        out.append("they replace a base game vehicle:")
        out.append("")
        for r in empty:
            out.append(f"- {r['resource']}")
        out.append("")

    return "\n".join(out)
