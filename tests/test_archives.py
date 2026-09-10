from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
sys.path.insert(0, str(HERE))

import rpf7_writer
import riddle_archives as ra
import riddle_core as core

try:
    import py7zr
except ImportError:
    py7zr = None


FAILURES = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def head(title):
    print(f"\n-- {title} --")


def tmp():
    return Path(tempfile.mkdtemp(prefix="rfvt_test_"))


def meta_for(model: str) -> bytes:
    return (
        "<?xml version='1.0'?><CVehicleModelInfo__InitDataList><InitDatas><Item>"
        f"<modelName>{model}</modelName><txdName>{model}</txdName>"
        "<handlingId>GRANGER</handlingId><gameName>POLGRANGER</gameName>"
        "<vehicleMakeName>DECLASSE</vehicleMakeName><vehicleClass>VC_SUV</vehicleClass>"
        "<type>VEHICLE_TYPE_CAR</type></Item></InitDatas>"
        "</CVehicleModelInfo__InitDataList>"
    ).encode()


def real_rpf(model: str) -> bytes:
    return rpf7_writer.build({
        "vehicles.meta": ("binary", meta_for(model)),
        f"{model}.yft": ("resource", b"MODEL" * 900),
        f"{model}.ytd": ("resource", b"TEX" * 700),
    })


def make_zip(path: Path, entries) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data if isinstance(data, bytes) else data.encode())
    return path


def build_fixtures(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)

    make_zip(root / "628156-Police_Granger_Classic__final_.zip", [
        ("polgrangerrto/dlc.rpf", real_rpf("polgrangerrto")),
        ("polgrangerrto/readme.txt", b"install with openiv"),
    ])
    make_zip(root / "wrapped.zip", [
        ("Police Granger Classic (final)/Add-On/fibgrangerrto/dlc.rpf",
         real_rpf("fibgrangerrto")),
    ])
    make_zip(root / "collection.zip", [
        ("Collection/carone/dlc.rpf", real_rpf("carone")),
        ("Collection/cartwo/dlc.rpf", real_rpf("cartwo")),
    ])
    make_zip(root / "loose.zip", [
        ("loosecar/vehicles.meta", meta_for("loosecar")),
        ("loosecar/loosecar.yft", b"\x00" * 2048),
        ("loosecar/loosecar.ytd", b"\x00" * 1024),
    ])
    make_zip(root / "duplicate_of_polgranger.zip", [
        ("polgrangerrto/dlc.rpf", real_rpf("polgrangerrto")),
    ])

    make_zip(root / "slip.zip", [("../../pwned.txt", "escaped"), ("ok/dlc.rpf", b"z" * 10)])
    make_zip(root / "bomb.zip", [("big.bin", b"\x00" * (200 * 1024 * 1024))])

    scratch = root / "_scratch"
    scratch.mkdir(exist_ok=True)
    blob = make_zip(scratch / "l5.zip", [("deep/dlc.rpf", b"d" * 10)]).read_bytes()
    for level in (4, 3, 2):
        blob = make_zip(scratch / f"l{level}.zip",
                        [(f"l{level + 1}.zip", blob)]).read_bytes()
    make_zip(root / "deepnest.zip", [("l2.zip", blob)])
    shutil.rmtree(scratch, ignore_errors=True)

    data = (root / "loose.zip").read_bytes()
    (root / "corrupt.zip").write_bytes(data[: len(data) // 2])

    shutil.copy(root / "loose.zip", root / "mislabelled.rar")
    (root / "real.rar").write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 200)

    with zipfile.ZipFile(root / "symlink.zip", "w") as archive:
        info = zipfile.ZipInfo("evil_link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "/etc/passwd")
        archive.writestr("ok/dlc.rpf", b"q" * 10)

    if py7zr is not None:
        stage = root / "_stage" / "grangersev"
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "dlc.rpf").write_bytes(real_rpf("grangersev"))
        with py7zr.SevenZipFile(root / "seven.7z", "w") as archive:
            archive.writeall(str(stage), "grangersev")
        shutil.rmtree(root / "_stage", ignore_errors=True)

    return root


def test_archives(fix: Path):
    head("backends available on this machine")
    print("  ", ra.backends())

    head("format comes from the header, not the extension")
    check("zip detected", ra.sniff(fix / "loose.zip") == "zip")
    check("rar5 detected", ra.sniff(fix / "real.rar") == "rar")
    check("a .rar that is really a zip reads as zip",
          ra.sniff(fix / "mislabelled.rar") == "zip")
    check("a non-archive reads as none", ra.sniff(fix) == "none")

    head("extraction")
    out = tmp()
    result = ra.extract(fix / "628156-Police_Granger_Classic__final_.zip", out)
    check("archive with a junk filename extracts", result["ok"], str(result.get("error", "")))
    check("content root steps past the wrapper folder",
          Path(result["root"]).name == "polgrangerrto", Path(result["root"]).name)

    result = ra.extract(fix / "mislabelled.rar", tmp())
    check("mislabelled .rar extracts as a zip", result["ok"], str(result.get("error", "")))

    if py7zr is not None:
        result = ra.extract(fix / "seven.7z", tmp())
        check("7z extracts", result["ok"], str(result.get("error", "")))
    else:
        print("  SKIP  7z - py7zr not installed")

    head("failures, deliberately triggered")
    out = tmp()
    result = ra.extract(fix / "slip.zip", out)
    check("zip-slip entry refused",
          any("outside the output folder" in p for p in result["problems"]),
          str(result["problems"]))
    check("nothing was written outside the output folder",
          not (out.parent / "pwned.txt").exists())
    check("the rest of the archive still extracted", result["ok"])

    result = ra.extract(fix / "bomb.zip", tmp(), max_bytes=8 * 1024 * 1024)
    check("size bomb aborted",
          not result["ok"] and "bomb" in result.get("error", ""), result.get("error", ""))

    result = ra.extract(fix / "corrupt.zip", tmp())
    check("truncated archive reported, not raised",
          not result["ok"], result.get("error", "")[:60])

    result = ra.extract(fix / "real.rar", tmp())
    if ra.backends()["rar"]:
        check("garbage rar reported by the installed unpacker",
              not result["ok"], result.get("error", "")[:80])
    else:
        check("no rar backend: refused with an actionable message",
              not result["ok"] and "7-Zip" in result.get("error", ""),
              result.get("error", ""))

    out = tmp()
    result = ra.extract(fix / "symlink.zip", out)
    check("symlink entry skipped",
          any("symlink" in p for p in result["problems"]), str(result["problems"]))
    check("no symlink on disk", not (out / "evil_link").is_symlink())

    head("nesting")
    out = tmp()
    result = ra.extract(fix / "deepnest.zip", out)
    check("the archive past MAX_DEPTH is not unpacked",
          not any(f.endswith("dlc.rpf") for f in result["files"]))
    left = list(out.rglob("*.zip"))
    check("it is left on disk rather than lost",
          len(left) == 1 and left[0].name == "l5.zip", str([p.name for p in left]))


def test_build(fix: Path):
    src = tmp()
    wanted = ["628156-Police_Granger_Classic__final_.zip", "wrapped.zip",
              "collection.zip", "loose.zip", "duplicate_of_polgranger.zip",
              "corrupt.zip", "real.rar"]
    if py7zr is not None:
        wanted.append("seven.7z")
    for name in wanted:
        shutil.copy(fix / name, src / name)
    out = tmp()

    head("preview stays cheap - nothing is unpacked yet")
    preview = core.probe_folders(src)
    check("no loose pack folders in a folder of archives", preview["total"] == 0)
    check("archives counted", preview["archives"]["total"] == len(wanted),
          str(preview["archives"]["total"]))
    check("unsupported archive named with a reason",
          any("real.rar" in u for u in preview["archives"]["unsupported"]),
          str(preview["archives"]["unsupported"]))
    check("nothing was unpacked during preview",
          not any(p.is_dir() for p in src.iterdir()))

    head("build")
    events = []
    result = core.build_batch(src, out, progress=lambda d, t, label: events.append(label))
    names = sorted(p.name for p in out.iterdir() if p.is_dir())
    print("   resources:", names)
    print("   archives:", {k: v for k, v in result["archives"].items() if k != "origins"})
    for note in result["archive_notes"]:
        print("   note:", note)

    check("resource named after the folder holding dlc.rpf",
          "polgrangerrto" in names, str(names))
    check("the archive filename is never used as a resource name",
          not any(n.startswith("628156") for n in names))
    check("a wrapper folder is not used either",
          "fibgrangerrto" in names and "police_granger_classic_final" not in names,
          str(names))
    check("one resource per dlc.rpf in a multi-pack archive",
          "carone" in names and "cartwo" in names, str(names))
    check("multi-pack archive reported",
          any("contains 2 packs" in n for n in result["archive_notes"]))
    check("a loose pack inside an archive builds", "loosecar" in names, str(names))
    if py7zr is not None:
        check("7z pack builds", "grangersev" in names, str(names))

    check("corrupt archive isolated, batch continued",
          any("corrupt.zip" in n for n in result["archive_notes"]) and result["built"] >= 4)
    check("unsupported rar reported with an actionable message",
          any("real.rar" in n and "7-Zip" in n for n in result["archive_notes"]))
    check("a second pack claiming a taken resource name is refused, not overwritten",
          any(not r["ok"] and "refusing to overwrite" in r.get("error", "")
              for r in result["results"]),
          next((r["error"] for r in result["results"]
                if not r["ok"] and "refusing" in r.get("error", "")), "")[:100])

    head("the extracted resource is real")
    resource = out / "polgrangerrto"
    check("fxmanifest written", (resource / "fxmanifest.lua").exists())
    check("model came out of the rpf", (resource / "stream/polgrangerrto.yft").exists())
    check("meta came out of the rpf", (resource / "data/vehicles.meta").exists())
    check("spawn code found",
          "polgrangerrto" in (resource / "spawncode.md").read_text(encoding="utf-8"))

    head("housekeeping")
    check("archive temp dirs removed",
          not list(Path(tempfile.gettempdir()).glob("rfe_arc_*")))
    check("nothing written beside the user's downloads",
          not any(p.is_dir() for p in src.iterdir()))
    check("both phases reported to the UI",
          any(e.startswith("unpacking") for e in events)
          and any(e.startswith("building") for e in events), str(events[:3]))

    head("no regression: a plain folder source is unaffected")
    plain = tmp()
    with zipfile.ZipFile(fix / "loose.zip") as archive:
        archive.extractall(plain)
    plain_result = core.build_batch(plain, tmp())
    check("folder source still builds with no archive work",
          plain_result["built"] == 1 and plain_result["archives"]["archives"] == 0,
          str(plain_result["archives"]))


def main():
    fixtures = build_fixtures(tmp() / "fixtures")
    test_archives(fixtures)
    test_build(fixtures)
    print("\n" + ("ALL PASS" if not FAILURES else "FAILURES: " + ", ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
