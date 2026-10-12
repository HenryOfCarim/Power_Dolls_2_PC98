> 🌐 **English** · [Українська](README.uk.md)

# pd2gfx — Power Dolls 2 (PC-98, Kogado 1994) graphics toolkit

Reverse-engineered decoder and extraction tools for the graphics of
*Power Dolls 2* (Kogado Software Products, PC-98, 1994).
Special editions like *Power Dolls 2 Dash* and *Advanced Power Dolls 2 Dash* should work too.

The codec and containers were recovered from the disassembler (`CONVERT.EXE`,
image offset `0x54E6`) and verified against all 360 raster images.
For palette help, see the note after Quick start.

---

## Status

| | status |
|---|---|
| Containers `.ASK`, `.PCK`, "raw block" | ✅ complete |
| Codec (LZSS) | ✅ complete, byte-exact |
| Plane / bit layout | ✅ proven from the GVRAM blit code |
| Extraction to PNG | ✅ 361 pictures (348 `.PCK` entries, 12 `.ASK` frames, the raw-block `S_ROLL.ASK`) |
| Palette mechanism | ✅ proven |
| Embedded 32-byte palettes in `.GCP` / `CHARA.PCK` | ✅ 26 `.GCP` palettes (2 custom) and 27 `CHARA.PCK` entries |
| Artwork screen palettes | ✅ 48-byte tables ship inside the EXEs (channel order B,R,G); `tools/pal_tables.py` can find them, see [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) |
| Colours of a plain `--all` run | ⚠️ **may be wrong** — the fallback is the PC-98 default ramp; see the palette note below |
| `.GCP` as a raster format | ❌ it is a GDC display list, not a picture |
| Compressor | ❌ not recovered (it is in `CONVERT.EXE`) |

---

## Requirements

Power Dolls 2 game. The convertor supports the game installed on FDI image or unpaked resources

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

If you have HDI disk images rather than an extracted game directory, unpack the
images first. `img_extract.py --all` searches recursively for supported disk
images (including `.HDI`) and gives each image its own output subdirectory.
Then `pd2extract.py --all` searches those extracted trees for `.PCK` and `.ASK`
graphics and writes PNGs:

```powershell
python tools\img_extract.py --all ..\hdi -o out\disks
python pd2extract.py --all out\disks out\png --palette auto
```

`--palette auto` applies a known screen palette when the `.PCK`/`.ASK` name gives
a clue (for example `FACE.PCK` → artwork); unknown names use the PC-98 default.
Use `--palette-dir DIR` if the game EXEs are outside the input tree.

For one HDI, pass its path directly, then point `pd2extract.py` at the extracted
folder:

```powershell
python tools\img_extract.py ..\hdi\PD2S.HDI -o out\disks\PD2S
python pd2extract.py --all out\disks\PD2S out\png --palette auto
```

For already extracted game files, the commands below assume the data directory
sits next to this repo (e.g. `..\hdi\PD2D`).

```powershell
# 1. everything from the game data dir -> PNG
#    no --pal/--pal-exe means the PC-98 default; see the palette note below
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

## Palette: if colours look wrong

If the image shape is right but the colours are wrong, choose the palette for the
screen where it appears. A plain `--all` run uses the PC-98 default ramp.

![FACE.PCK entry 0 rendered with the default, artwork, and gameplay palettes](docs/img/palette_default_vs_screen.png)

For example, `FACE.PCK` portraits use the artwork palette:

```powershell
python pd2extract.py --pck ..\hdi\PD2D\FACE.PCK out\face --pal-exe ..\hdi\PD2D\BRIEFING.EXE:0x234C6
```

`--all` applies one palette to every image in the run, so split runs by screen
when needed. For an unmapped screen, save a DOSBox-X screenshot with **Ctrl+F5**
and pass its `.pal` sidecar with `--pal`. See [`docs/PALETTE.md`](docs/PALETTE.md) and
[`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) for details.

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
                     [--palette pc98|gray|vivid|auto] [--palette-dir DIR]
                     [--pal FILE.pal]
                     [--pal-exe FILE.EXE:0xOFFSET] [--raw-geom WxH] [--scale N]
```

| option | effect |
|---|---|
| `--all DIR` | every `.PCK` and `.ASK` under DIR (recursive) |
| `--pck` / `--ask` | one archive / one file |
| `--palette pc98` | the PC-98 default ramp (used when no `--pal*` option is given) |
| `--palette gray` | greyscale — best for inspecting geometry |
| `--palette vivid` | high-contrast colours |
| `--palette auto` | choose a known screen palette from filename hints; unknown names use PC-98 default |
| `--palette-dir DIR` | EXE search directory for `--palette auto` (defaults to the input directory) |
| `--pal FILE.pal` | your own palette (JASC-PAL, raw 768 bytes, 48 bytes, or text) |
| `--pal-exe FILE.EXE:0xOFFSET` | use a 48-byte screen palette from an EXE; see the palette note above |
| `--raw-geom WxH` | geometry for a "raw block" `.ASK`; derived from `decoded_size` by default (`S_ROLL.ASK` → 640x320) |
| `--scale N` | integer upscale (nearest neighbour) |

For archives a subdirectory per archive is created; file names are
`<archive>_<index>.png`. A full `--all` run of the HDI data writes **361**
pictures: 348 `.PCK` entries, 12 `.ASK` frames and the raw-block `S_ROLL.ASK`.
`--palette auto` chooses a known palette from each `.PCK`/`.ASK` source name;
without a filename hint it keeps the PC-98 ramp. This is a per-file heuristic,
not confirmation of the palette used by a particular screen.

### `pd2pal.py` — palettes

```
python pd2pal.py --list  DIR                     # every palette in .PCK / .GCP entries
python pd2pal.py --suggest DIR [--for ASSET]      # heuristic screen-palette shortlist
python pd2pal.py --gcp   FILE.GCP  [-o OUT.pal]
python pd2pal.py --pck   FILE.PCK  [--entry N] [-o OUT.pal]
python pd2pal.py --read  FILE.pal                # read a DOSBox-X .pal
python pd2pal.py --shot  SHOT.png --vram Vga.bin [-o OUT.pal]
python pd2pal.py --default [-o OUT.pal]
                     [--fmt jasc|raw|nibbles]
```

`--suggest` scans EXE palette tables in an extracted game-data directory. With
`--for FACE.PCK`, filename keywords put the known artwork palette first; each
candidate shows its source and `--pal-exe` offset. The ordering is a heuristic,
not a confirmed mapping for that asset.

`--shot` derives the palette from a real screenshot by aligning it with the
GVRAM from a save state (`Vga.bin`). It prints a `confidence`; if that is low,
the screenshot and the save state are from different screens.
`--palette auto` uses the same filename hints and known EXE screen roles as
`pd2pal.py --suggest`; it is a per-file heuristic, not proof of the screen.
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
4. counts: 348 `.PCK` entries + 12 `.ASK` = 360 (plus the raw-block `S_ROLL.ASK`,
   which `pd2extract.py` renders as a 640x320 frame);
5. 26/26 `.GCP` carry a valid palette at offset `0xB`, exactly 2 of them
   non-default;
6. the four known screen palettes live inside the EXEs at the documented offsets
   (channel order B,R,G);
7. `S_ROLL.ASK` is a raw block and its geometry derives as 640x320.

```
python tools\verify.py --data "..\power dolls 2 dash HDI\_unpacked\PD2D" --floppy "..\power dolls 2 FDI\_unpacked"
```

### `tools/img_extract.py` — unpack a disk image

```
python tools\img_extract.py --probe IMAGE [IMAGE ...]
python tools\img_extract.py IMAGE -o OUTDIR [--base 0x1000]
python tools\img_extract.py --all IMAGEDIR -o OUTDIR
```

Its own FAT12/FAT16 reader, because several dumps defeat 98Bridge: plain FAT12
with media byte `0xFE` (`MS-DOS.FDI`), FAT12 behind a `0x1000`-byte wrapper (the
`S-Premium` and `Premium Disc` FDIs), and raw images whose boot sector is not at
offset 0. It reports the layout it found (`--probe`) and extracts the whole
directory tree. Images without a self-consistent BPB (the Advanced PD2 `.fdd`
set) are still scannable for palettes as opaque binaries.

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
| `.GCP` | header + **32-byte packed palette** + display list | `0x2B` | **no** — GDC commands |

Full breakdown: [`docs/FORMAT.md`](docs/FORMAT.md).

---

## Documentation

| file | contents |
|---|---|
| [`docs/FORMAT.md`](docs/FORMAT.md) | **deep dive:** all containers, the exact codec algorithm, state, bit reader, tokens, the two pitfalls, output layout, proof of correctness |
| [`docs/PALETTE.md`](docs/PALETTE.md) | palette basics: how to choose a screen palette, what the 32-byte `.GCP` ramp is, and how to render with the right colours |
| [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) | evidence and details for the 48-byte screen-palette tables inside the EXEs, channel order B,R,G, and how to find/extract them |
| [`docs/ADVANCED_PD2.md`](docs/ADVANCED_PD2.md) | Advanced PD2: the BPB-less `.fdd` layout, the `BIGFILE` container, and why this release is a patch over PD2 |
| [`docs/PD1.md`](docs/PD1.md) | Power Dolls 1: why only 6 pictures convert — the artwork lives in `.GCP` display lists (the same format as PD2's `CHARA.PCK`) |
| [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md) | display lists: the player routine (10 binaries, both games), the stream grammar, what is left |
| [`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.md) | HDI boot/load chain, `EXEC` map, decoder locations in 15 binaries, how to resolve DGROUP |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | the traps that derailed earlier investigations (so you do not repeat them) |
| [`docs/LIVE_PALETTE_DUMP.uk.md`](docs/LIVE_PALETTE_DUMP.uk.md) | (Ukrainian) live palette capture from DOSBox-X: the MCP tools (`dosbox_mcp_palette.py`, `mcp_probe.py`, `mcp_poll_palette.py`, `mcp_dump_vram.py`), `pal_from_shot.py`, and the closed "dumper inside the guest" experiment |

Retired tools live in [`_attic-tools/`](_attic-tools/MANIFEST.md) (moved, not
deleted, with per-file reasons and a one-command rollback).

Ukrainian originals: [`README.uk.md`](README.uk.md), `docs/*.uk.md`.

---

## Limitations

* **Palette:** raster entries usually lack a screen palette; without `--pal` or
  `--pal-exe`, the extractor uses the PC-98 default. `.GCP` is a GDC display
  list. See the palette note above.
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
