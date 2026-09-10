<div align="center">

<img src="web/logo.png" width="90" alt="Riddle-FUVT">

# Riddle-FUVT

### Riddle FiveM Ultimate Vehicle Tool

**Convert GTA V add-on vehicle packs into FiveM-ready resources — in batch.**

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?style=flat-square&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/license-Free%20use%20only-6FCF97?style=flat-square)](LICENSE)

</div>

---

## Install

1. Download this repository (**Code → Download ZIP**) and unzip it.
2. Double-click **`Riddle-FUVT.bat`**.

First launch finds Python 3.10+, builds a private `.venv` beside the app and
installs what it needs there. Takes a minute or two with no output while pip
works — that's normal.

| | |
|---|---|
| `Riddle-FUVT.bat --diag` | start with the dev console, for bug reports |
| `Riddle-FUVT.bat --repair` | rebuild the environment |
| `Riddle-FUVT.bat --check` | show what's installed, including 7-Zip / UnRAR |
| `Riddle-FUVT.bat --shortcut` | add a desktop shortcut |

---

## Extract

Point it at your `resources` folder. It parses every `vehicles.meta` and gives
you a searchable table of every spawn code on your server.

Select a folder → **Scan** → search or sort → pick a format → **Export**.

Formats: spawn codes (`.txt`), QBCore, Qbox, ESX SQL.

The QBCore export is a block of entries to paste inside the existing
`local Vehicles = {` in `qb-core/shared/vehicles.lua`. The Qbox export is a whole
`qbx_core/shared/vehicles.lua`.

Prices aren't in `vehicles.meta`, so they default to `0` — set a default in the
sidebar or edit rows inline before exporting.

---

## Build add-ons

Point it at a folder of vehicle packs. Each one becomes its own resource:

```
police_granger\
    stream\              .yft .ytd .ybn .ycd
    data\                vehicles.meta, carvariations, carcols, handling
    audioconfig\         .rel files
    sfx\<pack>\          .awc wavepacks
    labels.lua
    fxmanifest.lua
    spawncode.md
```

Plus a combined `spawncodes.md` with `/car` commands and `server.cfg` lines.
Downloads can stay as `.zip`, `.rar` or `.7z` — they're unpacked for you
(`.rar` needs 7-Zip or WinRAR installed; `.7z` needs `py7zr`, which setup adds).

**Do I need gtautil?** Usually not. Most mod `dlc.rpf` files store their table of
contents in the clear and unpack natively. Ones using AES or NG encryption hide
it behind keys inside `GTA5.exe` — those fall back to
[gtautil](https://github.com/indilo53/gtautil), and a download button appears
only if a pack actually needs it.

**Conversion fixes.** Siren IDs are deduplicated across the whole batch.
`gameName` is a text key, not a name, so it's rewritten and a `labels.lua`
generated. Handling generation is off by default — a `handlingId` pointing at a
base-game entry is legal, so you get a warning instead of invented tuning.

---

## Merge

Combines a folder of packs into a single resource. Works on raw packs and on
resources you're already running — it detects which and switches automatically.

**Only vehicles are merged.** Wheel packs, EUP, MLOs, maps and audio resources
are left exactly where they are and listed with a reason. A resource is merged
only when it lists vehicles in a meta **and** ships the `.yft` models for them.

**Escrow-protected resources are skipped.** A resource carrying a `.fxap` is a
Cfx escrow asset: its scripts are encrypted and the escrow is tied to that
resource's own name. Copied into a merged resource it simply will not start, and
no amount of copying `.fxap` files fixes it — each one is bound to its own asset,
not a shared key. Those resources are skipped, flagged in the log, and left
untouched where they are. Keep loading them from your `server.cfg` as before;
the merged pack sits alongside them.

**Non-game files are not copied.** Livery templates, `.psd`/`.dds` sources,
readmes and the like stay in the original resource — anything the manifest
actually declares is kept regardless.

**No meta is ever rewritten.** FiveM accepts repeated `data_file` entries and
scans `stream/` recursively, so each pack keeps its own subfolder and a meta
holding 300 cars goes in whole. Packs that shard their metas instead
(`vehicles_food.meta`) and declare them with a glob are expanded and declared
individually.

**Duplicate spawn codes never stop the run.** The same car shipped in two
collections is kept once. A genuinely *different* build sharing a spawn code is
renamed `name_1` … `name_10` — model files, `_hi` LODs, tuning parts, `modelName`,
`txdName`, `handlingId` and `handlingName` all follow. Engine audio does not: a
`.rel` stores a hash of the original name, so a renamed car keeps the old
binding. The log names every rename.

---

## Known limits

- **Windows only.** The RPF reader is portable Python; the GUI and gtautil aren't.
- **Replace-only vehicles** have no new spawn code. They build, but replace the
  original.
- **Gen 9 / Enhanced Edition** archives may not open — gtautil targets Legacy.
- **A pack whose model files don't match its `modelName`** is left out of a merge
  rather than merged wrongly. The log says which and why.
- **Escrow-protected (`.fxap`) resources cannot be merged** by any tool. They are
  skipped and keep running as separate resources.
- **The native RPF reader validates everything it writes**, but hasn't met every
  pack in the wild. If a build logs warnings, test that vehicle before shipping.

---

## License

**Free use only.** See [LICENSE](LICENSE). Use it, modify it, share it. Don't
sell it, paywall it, or remove the author credit. Files it *generates* are yours.

Built by **DanTheMan7777** — [github.com/DanRiddle](https://github.com/DanRiddle)

RPF7 format reference: [CodeWalker](https://github.com/dexyfex/CodeWalker) by
dexyfex. Encrypted archives via [gtautil](https://github.com/indilo53/gtautil) by
indilo53.
