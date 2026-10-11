> 🌐 **English** · [Українська](README.uk.md)

# pd2gfx — Power Dolls 2 (PC-98, Kogado 1994) graphics toolkit

Reverse-engineered decoder and extraction tools for the graphics of
*Power Dolls 2* (Kogado Software Products, PC-98, 1994).

The codec, the containers and the palette mechanism were recovered from the
disassembler (`CONVERT.EXE`, image offset `0x54E6`) and verified against all
360 images shipped with the game.

---

## Status

| | status |
|---|---|
| Containers `.ASK`, `.PCK`, "raw block" | ✅ complete |
| Codec (LZSS) | ✅ complete, byte-exact |
| Plane / bit layout | ✅ proven from the GVRAM blit code |
| Extraction to PNG | ✅ 361 pictures (348 `.PCK` entries, 12 `.ASK` frames, the raw-block `S_ROLL.ASK`) |
| Palette mechanism | ✅ proven |
| Palettes from `.GCP` / `CHARA.PCK` | ✅ (2 custom out of 26) |
| Palettes of the artwork screens (e.g. the equip screen) | ✅ the tables ship inside the EXEs (48 bytes, channel order B,R,G) — `tools/pal_tables.py`; a capture only says *which* table, see [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) |
| `.GCP` as a raster format | ❌ it is a GDC display list, not a picture |
| Compressor | ❌ not recovered (it is in `CONVERT.EXE`) |

---

## Requirements

```
Python 3.10+
Pillow            # PNG output
numpy             # only for pd2pal.py --shot and tools/render_vram.py
```

```powershell
pip install Pillow numpy
```

---

## Quick start

Assumes the game data directory sits next to this repo (e.g. `..\hdi\PD2D`).

```powershell
# 1. everything from the game data dir -> PNG (default PC-98 palette)
python pd2extract.py --all ..\hdi\PD2D out\png

# 2. a single archive
python pd2extract.py --pck ..\hdi\PD2D\FACE.PCK out\face

# 3. a single picture
python pd2extract.py --ask ..\hdi\PD2D\GAMEOVER.ASK out

# 4. the palettes that really are inside the files
python pd2pal.py --gcp ..\hdi\PD2D\HARDY.GCP -o out\hardy.pal
python pd2pal.py --list ..\hdi\PD2D

# 5. self-check (writes nothing, only verifies)
python tools\verify.py --data ..\hdi\PD2D
```

---

## Tools

### `pd2img.py` — library

The canonical codec implementation. Public API:

```python
from pd2img import (decode_lzss, parse_entry, parse_archive, parse_ask,
                    is_image_entry, planes_from_stream, indices_from_planes)

# archive -> [(index, blob)]
for i, blob in parse_archive("FACE.PCK"):
    if not is_image_entry(blob):
        continue                      # not a picture (see docs/FORMAT.md)
    r = parse_entry(blob)             # {'w','h','x','y','size','stream_bytes',...}
    planes = planes_from_stream(r['stream_bytes'], r['w'], r['h'])   # 4 x (w/8*h)
    idx    = indices_from_planes(planes, r['w'], r['h'])             # 1 byte/pixel
```

| function | purpose |
|---|---|
| `decode_lzss(data, start, outlen)` | the codec itself; returns `(bytes, bytes_consumed)` |
| `parse_entry(blob)` | parse one picture block |
| `parse_archive(path)` | parse a `.PCK` into entries |
| `parse_ask(path)` | parse a standalone `.ASK` |
| `is_image_entry(blob)` | does the block satisfy `decoded_size == w*h/2` |
| `planes_from_stream(...)` | stream → 4 bit planes |
| `indices_from_planes(...)` | planes → pixel indices (1 byte/pixel) |

### `pd2extract.py` — PNG dumper

```
python pd2extract.py (--all DIR | --pck FILE | --ask FILE) OUTDIR
                     [--palette pc98|gray|vivid] [--pal FILE.pal]
                     [--pal-exe FILE.EXE:0xOFFSET] [--raw-geom WxH] [--scale N]
```

| option | effect |
|---|---|
| `--all DIR` | every `.PCK` and `.ASK` under DIR (recursive) |
| `--pck` / `--ask` | one archive / one file |
| `--palette pc98` | the default PC-98 palette (default) |
| `--palette gray` | greyscale — best for inspecting geometry |
| `--palette vivid` | high-contrast colours |
| `--pal FILE.pal` | your own palette (JASC-PAL, raw 768 bytes, 48 bytes, or text) |
| `--pal-exe FILE.EXE:0xOFFSET` | **a real screen palette**, read from the 48-byte table inside an EXE — `BRIEFING.EXE:0x234C6` (equip artwork), `TACTICS.EXE:0x1ECA4` (gameplay), `PD2SHELL.EXE:0x98E6` (menu) |
| `--raw-geom WxH` | geometry for a "raw block" `.ASK`; derived from `decoded_size` by default (`S_ROLL.ASK` → 640x320) |
| `--scale N` | integer upscale (nearest neighbour) |

For archives a subdirectory per archive is created; file names are
`<archive>_<index>.png`. A full `--all` run of the HDI data writes **361**
pictures: 348 `.PCK` entries, 12 `.ASK` frames and the raw-block `S_ROLL.ASK`.

### `pd2pal.py` — palettes

```
python pd2pal.py --list  DIR                     # every palette in .PCK / .GCP entries
python pd2pal.py --gcp   FILE.GCP  [-o OUT.pal]
python pd2pal.py --pck   FILE.PCK  [--entry N] [-o OUT.pal]
python pd2pal.py --read  FILE.pal                # read a DOSBox-X .pal
python pd2pal.py --shot  SHOT.png --vram Vga.bin [-o OUT.pal]
python pd2pal.py --default [-o OUT.pal]
                     [--fmt jasc|raw|nibbles]
```

`--shot` derives the palette from a real screenshot by aligning it with the
GVRAM from a save state (`Vga.bin`). It prints a `confidence`; if that is low,
the screenshot and the save state are from different screens.
See [`docs/PALETTE.md`](docs/PALETTE.md).

### `tools/pal_tables.py` — the palette banks inside the EXEs

The screens' palettes are not stored next to their pixels, but the game ships
whole banks of 48-byte palettes inside its executables (channel order **B,R,G**).
This tool finds them, extracts them and locates the source of a live dump:

```
python tools\pal_tables.py --list  [--data DIR ...] [--out tables.txt]
python tools\pal_tables.py --dump  OUTDIR [--data DIR ...]
python tools\pal_tables.py --find  DUMP_analog.rgb
python tools\pal_tables.py --self-test
```

Found in the shipped HDI+FDI data: **127 tables in 22 files, 59 distinct
palettes** (e.g. `TACTICS.EXE 0x1ECA4` — the gameplay screen, `BRIEFING.EXE
0x234C6` — the shared artwork/equip palette, `PD2SHELL.EXE 0x98E6` — the menu).
See [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md).

### `pd2raw.py` — `.SLD` "raw blocks"

```
python pd2raw.py --file FILE.SLD -o OUT.bin
python pd2raw.py --all  DIR      -o OUTDIR
```

Same LZSS, but the container is just `u32 decoded_size` plus a stream from
offset 4. Every `.SLD` and also `S_ROLL.ASK` are built this way. Detection lives
in `pd2img.is_raw_block`, so `pd2extract.py` renders such a file as a picture
too (geometry from `decoded_size`, or `--raw-geom WxH`).

### `tools/verify.py` — self-check

Writes nothing; it verifies the claims made in [`docs/FORMAT.md`](docs/FORMAT.md)
and [`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.md):

1. the decoder sits at **exactly the documented addresses** in 7 HDI binaries
   and 8 floppy-release binaries (accounting for the two prologue forms);
2. it is **one library routine**: in 4 binaries the code is byte-identical to
   `CONVERT.EXE` (differences only inside `lcall` immediates), while
   `OPENING`/`REPORT` come from a different compilation — for those, 6
   distinctive codec constants are checked instead;
3. every picture entry decodes to exactly `decoded_size` and consumes the
   stream down to the last byte (1 byte of tolerance for the bit-buffer tail);
4. counts: 348 `.PCK` entries + 12 `.ASK` = 360;
5. 26/26 `.GCP` carry a valid palette at offset `0xB`, exactly 2 of them
   non-default.

```
python tools\verify.py --data ..\hdi\PD2D --floppy ..
```

### `tools/render_vram.py` — render GVRAM from a save state

```
python tools\render_vram.py dump\Vga.bin out\screen.png [--pal file.pal]
```

The mapping is non-obvious: `base = 0x07C000`, plane stride `0x10000`
(not the physical `0x8000`), each plane 400×80 bytes. With the wrong stride you
get noise.

---

## Formats — in brief

| extension | container | stream starts at | picture? |
|---|---|---|---|
| `.ASK` | `u32 decoded_size; u16 x,y,w,h` | 12 | yes (`S_ROLL.ASK` is a raw block instead) |
| `.PCK` | archive of entries, each like `.ASK` | 12 | mixed: some entries are display lists |
| `.SLD` | `u32 decoded_size` | 4 | no (data) |
| `.GCP` | header + **palette** + display list | 4 | **no** — GDC commands |

Full breakdown: [`docs/FORMAT.md`](docs/FORMAT.md).

---

## Documentation

| file | contents |
|---|---|
| [`docs/FORMAT.md`](docs/FORMAT.md) | **deep dive:** all containers, the exact codec algorithm, state, bit reader, tokens, the two pitfalls, output layout, proof of correctness |
| [`docs/PALETTE.md`](docs/PALETTE.md) | palette: mechanism, 32-byte format, where it is, where it is not, how to obtain it |
| [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) | **correction:** the screens' palettes *are* in the files — 48-byte banks inside the EXEs, channel order B,R,G, and how to find/extract them |
| [`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.md) | HDI boot/load chain, `EXEC` map, decoder locations in 15 binaries, how to resolve DGROUP |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | the traps that derailed earlier investigations (so you do not repeat them) |

Ukrainian originals: [`README.uk.md`](README.uk.md), `docs/*.uk.md`.

---

## Limitations

* **The screens' palettes are in the executables, not in the artwork.** They are
  48-byte tables (channel order B,R,G, banks every `0x60`/`0xC0` bytes) — extract
  them with `tools/pal_tables.py`, see [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md).
  A live dump is only needed to learn which table a screen uses. Extracted PNGs
  therefore have correct geometry, and correct colours once you pass the right
  table via `--pal`.
* **`.GCP` is not decoded** — it is a display list for the hardware GDC, not a
  raster format.
* **The compressor** was not recovered; it is in `CONVERT.EXE` (look next to
  the decoder at image `0x54E6`).
* Several archives contain no pictures at all (`MES`, `WMES`, `NAMES`, `MOJI`,
  `NPC`, `MUNIT`, `TUNIT`, `MAP_CHG`, `MISSON*D`, `SCEN_MIS`, `YAOUPD1`,
  `CHARA`, `ANIME`) — they hold text or display lists.

---

## Provenance

Everything was recovered by static analysis (a 16-bit DOS disassembler with
`lcall` resolution and DGROUP-relative string annotation), plus reading GVRAM
out of DOSBox-X save states. The decoder is byte-for-byte identical in 15
binaries (differences are only `lcall` immediates pointing at each build's
runtime), which confirms it is a single statically linked library routine.

The tools do not need the game itself — only its data files.

---

## Turning this into a git repository

```powershell
cd pd2gfx
git init
git add .
git commit -m "Power Dolls 2 (PC-98) graphics decoder and extraction tools"
```

`.gitignore` already excludes `out/` (generated output) and `__pycache__/`.
Game files are not part of the repository — the tools work with any copy of
`PD2D`, whose path is passed via `--data`.
