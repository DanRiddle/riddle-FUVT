from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
sys.path.insert(0, str(HERE))

import rpf7_writer
import riddle_core as core

FAILED = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   {detail}" if detail else ""))
    if not ok:
        FAILED.append(label)


def vehicles_meta(models) -> bytes:
    items = "\n".join(
        f"""    <Item>
      <modelName>{m}</modelName>
      <txdName>{m}</txdName>
      <handlingId>{m.upper()}</handlingId>
      <gameName>{m.upper()}</gameName>
      <vehicleMakeName>TESTCO</vehicleMakeName>
      <vehicleClass>VC_SUV</vehicleClass>
      <type>VEHICLE_TYPE_CAR</type>
    </Item>""" for m in models
    )
    return (f"<CVehicleModelInfo__InitDataList>\n  <InitDatas>\n{items}\n"
            "  </InitDatas>\n</CVehicleModelInfo__InitDataList>\n").encode()


def handling_meta(models) -> bytes:
    items = "\n".join(
        f"    <Item type=\"CHandlingData\">\n      <handlingName>{m.upper()}</handlingName>\n"
        f"      <fMass value=\"1800.0\" />\n    </Item>" for m in models
    )
    return (f"<CHandlingDataMgr>\n  <HandlingData>\n{items}\n"
            "  </HandlingData>\n</CHandlingDataMgr>\n").encode()


def make_pack_at(folder: Path, models, rpf_name: str = "dlc.rpf") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    files = {"vehicles.meta": ("binary", vehicles_meta(models)),
             "handling.meta": ("binary", handling_meta(models))}
    for m in models:
        files[f"{m}.yft"] = ("resource", b"body" + m.encode())
    (folder / rpf_name).write_bytes(rpf7_writer.build(files))
    return folder


def make_pack(root: Path, pack_name: str, models, extras=()) -> Path:
    files = {
        "vehicles.meta": ("binary", vehicles_meta(models)),
        "handling.meta": ("binary", handling_meta(models)),
    }
    for m in models:
        files[f"{m}.yft"] = ("resource", b"body" + m.encode())
        files[f"{m}_hi.yft"] = ("resource", b"hi" + m.encode())
        files[f"{m}.ytd"] = ("resource", b"txd" + m.encode())
        files[f"{m}+hi.ytd"] = ("resource", b"hitxd" + m.encode())
    for name, payload in extras:
        files[name] = ("binary", payload)

    folder = root / pack_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dlc.rpf").write_bytes(rpf7_writer.build(files))
    return folder


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="merge_test_"))
    src = tmp / "packs"
    out = tmp / "out"
    src.mkdir(parents=True)

    try:
        make_pack(src, "charger2020", ["charger2020"])
        fleet = [f"polcar{i}" for i in range(1, 13)]
        make_pack(src, "police_fleet", fleet)
        make_pack(src, "granger_rto", ["polgrangerrto"])

        print("-- merge --")
        result = core.merge_batch(src, out, "", "mega_pack",
                                  {"fix_ids": True, "add_labels": True})
        check("merge succeeded", result.get("ok"), result.get("error", ""))
        if not result.get("ok"):
            return 1

        target = Path(result["path"])
        check("one resource, not three", result["packs"] == 3 and target.is_dir(),
              f"{result['packs']} packs -> {target.name}")
        check("every vehicle detected", result["vehicles"] == 14,
              f"{result['vehicles']} vehicles")

        print("\n-- the 12-car meta is intact, not split --")
        fleet_meta = target / "data" / "police_fleet" / "vehicles.meta"
        check("the pack's vehicles.meta exists as one file", fleet_meta.is_file())
        body = read(fleet_meta)
        check("all 12 <Item> blocks still in it", body.count("<modelName>") == 12,
              f"{body.count('<modelName>')} models")
        for m in fleet:
            if m not in body:
                check(f"{m} survived", False)
                break
        else:
            check("every one of the 12 models survived", True)
        check("no per-vehicle meta folders were created",
              not (target / "data" / "polcar1").exists())

        print("\n-- packs stay apart, model files stay together --")
        check("charger files in their own folder",
              (target / "stream" / "charger2020" / "charger2020.yft").is_file())
        check("granger files in their own folder",
              (target / "stream" / "granger_rto" / "polgrangerrto.yft").is_file())
        for suffix in ("_hi.yft", ".ytd", "+hi.ytd"):
            p = target / "stream" / "granger_rto" / f"polgrangerrto{suffix}"
            if not p.is_file():
                check(f"polgrangerrto{suffix} travelled with its model", False)
                break
        else:
            check("_hi / .ytd / +hi variants all travelled with their model", True)

        print("\n-- the manifest --")
        manifest = read(target / "fxmanifest.lua")
        check("one data_file per pack vehicles.meta",
              manifest.count("VEHICLE_METADATA_FILE") == 3,
              f"{manifest.count('VEHICLE_METADATA_FILE')} entries")
        check("handling listed per pack",
              manifest.count("HANDLING_FILE") == 3)
        check("paths are namespaced by pack",
              "data/police_fleet/vehicles.meta" in manifest)
        missing = [line.strip().strip("',")
                   for line in manifest.splitlines()
                   if line.strip().startswith("'") and line.strip().endswith("',")
                   and not (target / line.strip().strip("',")).exists()
                   and "*" not in line]
        check("every file{} entry exists on disk", not missing, str(missing[:3]))

        print("\n-- spawn sheet --")
        sheet = read(target / "spawncode.md")
        check("sheet lists all 14", all(m in sheet for m in fleet + ["charger2020", "polgrangerrto"]))

        print("\n-- duplicate spawn codes never stop the run --")
        dup_src = tmp / "dupes"
        dup_out = tmp / "dupes_out"
        dup_src.mkdir()
        make_pack(dup_src, "pack_a", ["police3"])
        make_pack(dup_src, "pack_b", ["police3"])
        dup = core.merge_batch(dup_src, dup_out, "", "dupe_pack", {})
        check("it finished instead of pausing",
              dup.get("ok") is True and not dup.get("needs_confirm"),
              dup.get("error", ""))
        check("the identical car was kept once, not duplicated",
              dup["vehicles"] == 1, str(dup["vehicles"]))
        check("and it says why",
              any("identical copy" in w for w in dup["warnings"]),
              str(dup["warnings"])[:120])
        check("both packs still kept their own folders",
              (Path(dup["path"]) / "data" / "pack_a").is_dir()
              and (Path(dup["path"]) / "data" / "pack_b").is_dir())

        print("\n-- a different build of the same code is renamed, not dropped --")
        diff_src = tmp / "diff"
        diff_src.mkdir()
        make_pack(diff_src, "stock", ["mf1"])
        tuned = diff_src / "tuned"
        tuned.mkdir(parents=True)
        files = {"vehicles.meta": ("binary", vehicles_meta(["mf1"])),
                 "handling.meta": ("binary", handling_meta(["mf1"]))}
        for suffix in ("", "_hi", "_spoiler_1"):
            files[f"mf1{suffix}.yft"] = ("resource", b"A-COMPLETELY-DIFFERENT-BUILD")
        (tuned / "dlc.rpf").write_bytes(rpf7_writer.build(files))

        res = core.merge_batch(diff_src, tmp / "diff_out", "", "diff_pack", {})
        check("merge finished", res.get("ok"), res.get("error", ""))
        check("both cars survive under different codes", res["vehicles"] == 2,
              str(sorted(v["model"] for v in res["vehicle_rows"])))
        check("the rename is reported",
              any(r["from"] == "mf1" and r["to"] == "mf1_1" for r in res.get("renames", [])),
              str(res.get("renames")))

        merged = Path(res["path"])
        check("the model file was renamed",
              (merged / "stream" / "tuned" / "mf1_1.yft").is_file())
        check("so was its _hi LOD",
              (merged / "stream" / "tuned" / "mf1_1_hi.yft").is_file())
        check("and its tuning part",
              (merged / "stream" / "tuned" / "mf1_1_spoiler_1.yft").is_file())
        check("the original pack is untouched",
              (merged / "stream" / "stock" / "mf1.yft").is_file())
        body = read(merged / "data" / "tuned" / "vehicles.meta")
        check("modelName follows the rename", "<modelName>mf1_1</modelName>" in body)
        check("txdName follows too", "<txdName>mf1_1</txdName>" in body)
        check("handlingId follows", "<handlingId>MF1_1</handlingId>" in body)
        hand = read(merged / "data" / "tuned" / "handling.meta")
        check("handlingName follows", "<handlingName>MF1_1</handlingName>" in hand)
        check("the audio caveat is stated",
              any("audio still binds" in w for w in res["warnings"]),
              str([w for w in res["warnings"] if "audio" in w])[:120])
        sheet = read(merged / "spawncode.md")
        check("both codes reach the sheet", "mf1" in sheet and "mf1_1" in sheet)

        print("\n-- two packs with the same folder name do not collide --")
        same = tmp / "same"
        same_out = tmp / "same_out"
        (same / "v1").mkdir(parents=True)
        (same / "v2").mkdir(parents=True)
        make_pack(same / "v1", "gtr", ["gtr35"])
        make_pack(same / "v2", "gtr", ["gtr35r"])
        res = core.merge_batch(same, same_out, "", "same_pack", {})
        check("both were kept under distinct subfolders",
              res.get("ok") and len({s["sub"] for s in res["sources"]}) == 2,
              str([s["sub"] for s in res.get("sources", [])]))

        print("\n-- every vehicle survives, however the packs are nested --")
        nest = tmp / "nested"
        nest_out = tmp / "nested_out"
        make_pack_at(nest / "single", ["carA"])
        for i in range(1, 6):
            make_pack_at(nest / "bundle" / f"unit{i}", [f"unit{i}"])
        make_pack_at(nest / "three_in_one", ["m1", "m2", "m3"])
        make_pack_at(nest / "two_rpf", ["twin1"], "a.rpf")
        make_pack_at(nest / "two_rpf", ["twin2"], "b.rpf")
        expected = (["carA"] + [f"unit{i}" for i in range(1, 6)]
                    + ["m1", "m2", "m3", "twin1", "twin2"])

        res = core.merge_batch(nest, nest_out, "", "nested_pack", {})
        check("merge ran", res.get("ok"), res.get("error", ""))
        check("every vehicle counted", res["vehicles"] == len(expected),
              f"{res['vehicles']} of {len(expected)}")

        got = {r["model"] for r in res["vehicle_rows"]}
        check("a bundle of five nested packs keeps all five",
              all(f"unit{i}" in got for i in range(1, 6)),
              str(sorted(m for m in got if m.startswith("unit"))))
        check("two .rpf side by side both survive",
              "twin1" in got and "twin2" in got)
        check("a single meta holding three keeps all three",
              all(m in got for m in ("m1", "m2", "m3")))
        check("nothing was lost", got == set(expected),
              f"missing {sorted(set(expected) - got)}")

        merged = Path(res["path"])
        metas = sorted(p.relative_to(merged).as_posix()
                       for p in merged.rglob("vehicles.meta"))
        check("one meta per pack reached the output", len(metas) == 9, str(len(metas)))
        man = read(merged / "fxmanifest.lua")
        check("every meta is declared in the manifest",
              man.count("VEHICLE_METADATA_FILE") == len(metas),
              f"{man.count('VEHICLE_METADATA_FILE')} entries for {len(metas)} files")
        sheet = read(merged / "spawncode.md")
        check("all of them reach spawncode.md",
              all(m in sheet for m in expected),
              str([m for m in expected if m not in sheet]))

        print("\n-- build: a bundle becomes one resource per pack --")
        b = core.build_batch(nest / "bundle", tmp / "nested_build", "", "",
                             {"spawn_sheet": True})
        check("five packs, five resources", b["built"] == 5, f"{b['built']} built")
        check("each holds its own car",
              sorted(m for r in b["results"] for m in r.get("models", []))
              == [f"unit{i}" for i in range(1, 6)],
              str(sorted(m for r in b["results"] for m in r.get("models", []))))

        print("\n-- build: one folder holding two .rpf keeps both, and says so --")
        b2 = core.build_batch(nest, tmp / "tworpf_build", "", "", {"spawn_sheet": True})
        two = next((r for r in b2["results"] if r.get("resource") == "two_rpf"), None)
        check("the two_rpf pack built", two is not None and two.get("ok"),
              str(two.get("error") if two else "not found"))
        if two and two.get("ok"):
            check("both vehicles reported",
                  sorted(two.get("models", [])) == ["twin1", "twin2"],
                  str(sorted(two.get("models", []))))
            check("the second meta is reported, not dropped in silence",
                  any("more than one" in w for w in two.get("warnings", [])),
                  str(two.get("warnings", []))[:140])
            sheet2 = read(Path(two["path"]) / "spawncode.md")
            check("both reach spawncode.md", "twin1" in sheet2 and "twin2" in sheet2)

        print("\n-- wheel / livery / tuning packs are not counted as vehicles --")
        mix = tmp / "mixed"
        mix_out = tmp / "mixed_out"
        make_pack_at(mix / "granger", ["polgranger"])
        make_pack_at(mix / "charger", ["charger20"])
        (mix / "rims").mkdir(parents=True)
        (mix / "rims" / "dlc.rpf").write_bytes(rpf7_writer.build({
            "vehicles.meta": ("binary", vehicles_meta(["adder", "sultan", "kuruma"])),
            "wheel_01.ytd": ("resource", b"w1"),
            "wheel_02.ytd": ("resource", b"w2"),
        }))
        (mix / "tuning").mkdir(parents=True)
        (mix / "tuning" / "dlc.rpf").write_bytes(rpf7_writer.build({
            "vehicles.meta": ("binary", vehicles_meta(["mycar", "adder", "sultan"])),
            "mycar.yft": ("resource", b"m"),
        }))

        res = core.merge_batch(mix, mix_out, "", "mixed_pack", {})
        check("merge ran", res.get("ok"), res.get("error", ""))
        got = sorted(r["model"] for r in res["vehicle_rows"])
        check("only real vehicles counted", got == ["charger20", "mycar", "polgranger"], str(got))
        left = {a["name"]: a["reason"] for a in res.get("left_alone", [])}
        check("the rim pack was left alone, not merged", "rims" in left, str(sorted(left)))
        check("and it says why", "model" in left.get("rims", ""), left.get("rims", ""))
        check("the tuning pack keeps its one real car, drops the three references",
              next(s for s in res["sources"] if s["sub"] == "tuning")["vehicles"] == 1
              and next(s for s in res["sources"] if s["sub"] == "tuning")["referenced"] == 2)

        merged = Path(res["path"])
        check("no wheel files were pulled into the merged resource",
              not (merged / "stream" / "rims").exists())
        check("the rim pack is untouched where it was",
              (mix / "rims" / "dlc.rpf").is_file())
        sheet3 = read(merged / "spawncode.md")
        check("no phantom spawn codes in the sheet",
              "adder" not in sheet3 and "sultan" not in sheet3 and "kuruma" not in sheet3)

        print("\n-- the same car in two packs counts once, like Extract --")
        dupe2 = tmp / "twice"
        make_pack_at(dupe2 / "granger", ["polgranger"])
        make_pack_at(dupe2 / "granger_v2", ["polgranger"])
        res = core.merge_batch(dupe2, tmp / "twice_out", "", "twice_pack",
                               {})
        check("counted once, not twice", res["vehicles"] == 1, str(res["vehicles"]))

        print("\n-- already-built resources take the resource-aware path --")
        lib = tmp / "library"
        lib_out = tmp / "library_out"

        def write(path: Path, text: str):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        def blob(path: Path, data: bytes):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        cars = lib / "lore-vehicles"
        write(cars / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\n"
              "client_script 'vehicle_names.lua'\n"
              "data_file 'VEHICLE_METADATA_FILE' 'data/vehicles.meta'\n")
        write(cars / "vehicle_names.lua", "AddTextEntry('EUROS','Euros')")
        write(cars / "data" / "vehicles.meta",
              vehicles_meta(["euros", "kawaii"]).decode())
        for m in ("euros", "kawaii"):
            blob(cars / "stream" / f"{m}.yft", b"model")
        snd = cars / "[sounds]" / "euros"
        write(snd / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\nclient_script 'audio.lua'\n")
        write(snd / "audio.lua", "-- engine sound")
        rims = lib / "wheels-pack"
        write(rims / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\nclient_script 'client.lua'\n"
              "data_file 'CARCOLS_FILE' 'data/carcols.meta'\n")
        write(rims / "client.lua", "-- wheels")
        write(rims / "data" / "carcols.meta", "<CVehicleModelInfoVarGlobal/>")
        for n in ("asbo_wl", "astron_wl"):
            blob(rims / "stream" / f"{n}.ydr", b"wheel")

        write(lib / "eup-clothing" / "fxmanifest.lua", "fx_version 'cerulean'\ngame 'gta5'\n")
        blob(lib / "eup-clothing" / "stream" / "mp_m_freemode_01^0.ydd", b"eup")
        write(lib / "mlo-police" / "fxmanifest.lua", "fx_version 'cerulean'\ngame 'gta5'\n")
        blob(lib / "mlo-police" / "stream" / "police.ytyp", b"mlo")
        write(lib / "handling-tweaks" / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\n"
              "data_file 'VEHICLE_METADATA_FILE' 'data/vehicles.meta'\n")
        write(lib / "handling-tweaks" / "data" / "vehicles.meta",
              vehicles_meta(["adder", "sultan"]).decode())

        res = core.merge_batch(lib, lib_out, "", "library_pack", {})
        check("auto-detected as built resources", res.get("mode") == "resources",
              str(res.get("mode")))
        check("only the vehicle resource was merged", res["packs"] == 1, str(res["packs"]))
        check("its vehicles counted", res["vehicles"] == 2, str(res["vehicles"]))

        left = {a["name"] for a in res["left_alone"]}
        for name in ("wheels-pack", "euros", "eup-clothing", "mlo-police", "handling-tweaks"):
            check(f"{name} left alone", name in left, str(sorted(left)))
        check("each says why it was left",
              all(a["reason"] for a in res["left_alone"]))

        merged = Path(res["path"])
        for name in ("wheels-pack", "eup-clothing", "mlo-police", "handling-tweaks"):
            check(f"{name} was not pulled into the merged resource",
                  not (merged / name).exists())
        check("no wheel drawables in the merged stream",
              not any(p.name.endswith("_wl.ydr") for p in merged.rglob("*.ydr")))
        check("the originals are untouched where they were",
              all((lib / n).is_dir() for n in
                  ("wheels-pack", "eup-clothing", "mlo-police", "handling-tweaks")))

        check("the vehicle resource's own script came across",
              any(p.name == "vehicle_names.lua" for p in merged.rglob("*.lua")))
        man = read(merged / "fxmanifest.lua")
        check("its script is declared", "client_script" in man)
        check("data_file type came from the source manifest",
              "VEHICLE_METADATA_FILE" in man)
        check("nothing was re-extracted or rebuilt",
              (merged / "stream" / "lore-vehicles" / "euros.yft").read_bytes() == b"model")
        missing = [l.strip().strip("',") for l in man.splitlines()
                   if l.strip().startswith("'") and l.strip().endswith("',")
                   and "*" not in l and not (merged / l.strip().strip("',")).exists()]
        check("every file{} entry exists on disk", not missing, str(missing[:3]))

        print("\n-- stacked metas: many cars in one file, and split-out variants --")
        stack = tmp / "stacked"
        big = stack / "vanillaworks"
        many = [f"vw{i}" for i in range(1, 41)]
        write(big / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\n"
              "data_file 'VEHICLE_METADATA_FILE' 'data/**/vehicles*.meta'\n"
              "data_file 'HANDLING_FILE' 'data/**/handling*.meta'\n")
        write(big / "data" / "Required" / "vehicles.meta", vehicles_meta(many).decode())
        write(big / "data" / "Required" / "handling.meta", handling_meta(many).decode())
        write(big / "data" / "Scenarios" / "vehicles_food.meta",
              vehicles_meta(["vws_food1", "vws_food2"]).decode())
        write(big / "data" / "Scenarios" / "vehicles_rally.meta",
              vehicles_meta(["vws_rally1"]).decode())
        write(big / "data" / "Scenarios" / "handling_food.meta",
              handling_meta(["vws_food1", "vws_food2"]).decode())
        for m in many + ["vws_food1", "vws_food2", "vws_rally1"]:
            blob(big / "stream" / f"{m}.yft", b"model")

        res = core.merge_batch(stack, tmp / "stacked_out", "", "stacked_pack", {})
        check("merge ran", res.get("ok"), res.get("error", ""))
        check("all 43 counted: 40 stacked + 3 in split files",
              res["vehicles"] == 43, str(res["vehicles"]))

        merged = Path(res["path"])
        man = read(merged / "fxmanifest.lua")
        check("the 40-car meta arrived as one file, not split",
              (merged / "data" / "vanillaworks" / "Required" / "vehicles.meta").is_file())
        body = read(merged / "data" / "vanillaworks" / "Required" / "vehicles.meta")
        check("all 40 <Item> blocks intact", body.count("<modelName>") == 40,
              str(body.count("<modelName>")))
        check("the glob was expanded, not copied literally", "**" not in man)
        for f in ("vehicles.meta", "vehicles_food.meta", "vehicles_rally.meta"):
            check(f"{f} declared as VEHICLE_METADATA_FILE",
                  any("VEHICLE_METADATA_FILE" in l and l.rstrip().endswith(f + "'")
                      for l in man.splitlines()),
                  next((l.strip() for l in man.splitlines() if f in l and "data_file" in l), "MISSING"))
        check("handling_food.meta got the handling type",
              any("HANDLING_FILE" in l and "handling_food.meta" in l for l in man.splitlines()))
        sheet = read(merged / "spawncode.md")
        check("the split-out cars reach spawncode.md",
              all(m in sheet for m in ("vws_food1", "vws_food2", "vws_rally1")))
        check("so do the stacked ones", all(m in sheet for m in many))

        print("\n-- and the Extract tab sees them too --")
        scanned = core.scan_folder(stack)
        found = {v["model"] for v in scanned["vehicles"]}
        check("Extract finds the split-out metas",
              {"vws_food1", "vws_food2", "vws_rally1"} <= found,
              str(sorted(found - set(many))))
        check("Extract total matches the merge", len(found) == 43, str(len(found)))

        print("\n-- non-game files are left behind --")
        jk = tmp / "junk"
        write(jk / "car" / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\nclient_script 'names.lua'\n"
              "files { 'ui/logo.png' }\n"
              "data_file 'VEHICLE_METADATA_FILE' 'data/vehicles.meta'\n")
        write(jk / "car" / "names.lua", "-- labels")
        write(jk / "car" / "data" / "vehicles.meta", vehicles_meta(["jcar"]).decode())
        blob(jk / "car" / "stream" / "jcar.yft", b"model")
        blob(jk / "car" / "template.dds", b"DDS ")
        blob(jk / "car" / "template.psd", b"8BPS")
        write(jk / "car" / "README.txt", "how to edit")
        write(jk / "car" / "version", "1.0")
        blob(jk / "car" / "ui" / "logo.png", b"PNG-DECLARED")

        res = core.merge_batch(jk, tmp / "junk_out", "", "junk_pack", {})
        check("merge ran", res.get("ok"), res.get("error", ""))
        check("the non-game files were counted", res.get("skipped_files") == 4,
              str(res.get("skipped_files")))
        merged = Path(res["path"])
        names = {p.name for p in merged.rglob("*") if p.is_file()}
        for junk in ("template.dds", "template.psd", "README.txt", "version"):
            check(f"{junk} not copied", junk not in names)
        check("a .png declared in files{} is still kept", "logo.png" in names, str(sorted(names)))
        check("the script still came across", "names.lua" in names)
        check("the vehicle still merged", res["vehicles"] == 1)

        print("\n-- escrow-protected resources are never merged --")
        esc = tmp / "escrow"
        write(esc / "free-car" / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\n"
              "data_file 'VEHICLE_METADATA_FILE' 'data/vehicles.meta'\n")
        write(esc / "free-car" / "data" / "vehicles.meta", vehicles_meta(["freecar"]).decode())
        blob(esc / "free-car" / "stream" / "freecar.yft", b"model")
        write(esc / "paid-car" / "fxmanifest.lua",
              "fx_version 'cerulean'\ngame 'gta5'\n"
              "data_file 'VEHICLE_METADATA_FILE' 'data/vehicles.meta'\n")
        write(esc / "paid-car" / "data" / "vehicles.meta", vehicles_meta(["paidcar"]).decode())
        blob(esc / "paid-car" / "stream" / "paidcar.yft", b"model")
        blob(esc / "paid-car" / ".fxap", b"\x00escrow")

        res = core.merge_batch(esc, tmp / "escrow_out", "", "escrow_pack", {})
        check("merge finished", res.get("ok"), res.get("error", ""))
        check("only the unprotected car merged", res["vehicles"] == 1, str(res["vehicles"]))
        check("the protected one is counted as escrowed", res.get("escrowed") == 1,
              str(res.get("escrowed")))
        check("its reason names the escrow",
              any(a.get("escrow") and ".fxap" in a["reason"] for a in res["left_alone"]),
              str([a["reason"] for a in res["left_alone"]])[:110])
        merged = Path(res["path"])
        check("none of its files reached the merged resource",
              not any("paidcar" in p.name for p in merged.rglob("*")))
        check("it is untouched where it was", (esc / "paid-car" / ".fxap").is_file())

        print("\n-- a folder with no vehicle resources at all --")
        assets = tmp / "assets_only"
        write(assets / "wheels" / "fxmanifest.lua", "fx_version 'cerulean'\ngame 'gta5'\n")
        blob(assets / "wheels" / "stream" / "x_wl.ydr", b"w")
        res = core.merge_batch(assets, tmp / "assets_out", "", "nothing", {})
        check("refused with a clear reason", res.get("ok") is False
              and "No vehicle resources" in res.get("error", ""), res.get("error", ""))
        check("it still lists what it found", len(res.get("left_alone", [])) == 1)

        print("\n-- empty folder is reported, not crashed on --")
        empty = tmp / "empty"
        empty.mkdir()
        res = core.merge_batch(empty, tmp / "empty_out", "", "x", {})
        check("reported as no packs found", res.get("ok") is False and "No vehicle packs" in res.get("error", ""))

        print()
        if FAILED:
            print(f"FAILED: {len(FAILED)}")
            for f in FAILED:
                print(f"  - {f}")
            return 1
        print("ALL PASS")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
