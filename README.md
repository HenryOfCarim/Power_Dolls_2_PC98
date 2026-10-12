> 🌐 **English** · [Українська](README.uk.md)

# pd2gfx — Power Dolls 2 (PC-98, Kogado 1994) graphics toolkit

Reverse-engineered decoder and extraction tools for the graphics of
*Power Dolls 2* (Kogado Software Products, PC-98, 1994).
Special editions like *Power Dolls 2 Dash* and *Advanced Power Dolls 2 Dash* should work too.

The codec and containers were recovered from the disassembler (`CONVERT.EXE`,
image offset `0x54E6`) and verified against all 360 raster images. The `.GCP` /
`CHARA.PCK` display lists are decoded too — they turned out to be GRCG tile
streams with XOR-delta rows, not rasters. For palette help, see the note after
Quick start.

---

## Status

| | status |
|---|---|
| Containers `.ASK`, `.PCK`, "raw block" | ✅ complete |
| Codec (LZSS) | ✅ complete, byte-exact |
| Plane / bit layout | ✅ proven from the GVRAM blit code |
| Extraction to PNG | ✅ 361 pictures (348 `.PCK` entries, 12 `.ASK` frames, the raw-block `S_ROLL.ASK`) |
| **Display lists** (`.GCP`, `CHARA.PCK`) | ✅ **decoded** — 77 blocks render to PNG with `pd2gcp.py` |
| **Advanced PD2 bundle** (`PD2DT.IDX` + `.BND`) | ✅ **solved** — 169 members, 74 `.PCK` + 39 `.GCP` + 9 `.ASK` + 6 `.SLD`, carved by `pd2bnd.py` |
| Palette mechanism | ✅ proven |
| Embedded 32-byte palettes in `.GCP` / `CHARA.PCK` | ✅ 26 `.GCP` palettes (2 custom) and 27 `CHARA.PCK` entries |
| Artwork screen palettes | ✅ 48-byte tables ship inside the EXEs (channel order B,R,G); `tools/pal_tables.py` can find them, see [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) |
| Colours of a plain `--all` run | ⚠️ **may be wrong** — the fallback is the PC-98 default ramp; see the palette note below |
| `.GCP` as a raster format | ✅ it is a GRCG display list, and it renders — see [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md) |
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
Use `--palette-dir DIR` if the game EXEs are outside the input tree. To assign a
specific `.pal` file to a source such as `M_CLR.PCK`, provide a JSON file with
`--palette-map`:

```json
{
  "M_CLR": "out/palettes/REPORT.EXE_0138b7.pal"
}
```

Save this as `palette-map.json` at the project root, then pass it while
extracting. Palette paths in the JSON are relative to the JSON file's directory:

```powershell
python pd2extract.py --all out\disks out\png --palette auto --palette-map palette-map.json
```

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

# 6. the display lists: .GCP files and CHARA.PCK
python pd2gcp.py --gcp ..\hdi\PD2D\KOGADO.GCP out\kogado
python pd2gcp.py --pck ..\hdi\PD2D\CHARA.PCK out\chara --entry 0
python pd2gcp.py --all ..\hdi\PD2D out\display-list
```

The display lists deserve one more line: PD1's `.GCP` carry no palette of their
own, and the `CHARA.PCK` portraits are drawn with the shared artwork palette
rather than the table inside the block, so those two sets want `--pal-exe`:

```powershell
python pd2gcp.py --all "..\power dolls 1\_unpacked" out\pd1 --pal-exe "..\power dolls 1\_unpacked\PREMIUM.EXE:0xEDF1"
python pd2gcp.py --pck ..\hdi\PD2D\CHARA.PCK out\chara --pal-exe ..\hdi\PD2D\BRIEFING.EXE:0x234C6
```

When you do not want to guess which palette belongs to which screen, brute-force
it: `pd2sweep.py` unpacks everything it finds, collects every palette it can find
and writes one labelled contact sheet per picture.

```powershell
python pd2sweep.py --data ..\hdi\PD2D -o out\sweep
python pd2sweep.py --image ..\hdi\PD2S.HDI -o out\sweep --orders all
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
                     [--palette pc98|gray|vivid|auto] [--palette-dir DIR] [--palette-map FILE.json]
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
| `--palette-map FILE.json` | custom source basename or full filename to `.pal` mapping; only with `auto`, relative paths use the JSON directory |
| `--pal FILE.pal` | your own palette (JASC-PAL, raw 768 bytes, 48 bytes, or text) |
| `--pal-exe FILE.EXE:0xOFFSET` | use a 48-byte screen palette from an EXE; see the palette note above |
| `--raw-geom WxH` | geometry for a "raw block" `.ASK`; derived from `decoded_size` by default (`S_ROLL.ASK` → 640x320) |
| `--scale N` | integer upscale (nearest neighbour) |

For archives a subdirectory per archive is created; file names are
`<archive>_<index>.png`. A full `--all` run of the HDI data writes **361**
pictures: 348 `.PCK` entries, 12 `.ASK` frames and the raw-block `S_ROLL.ASK`.
`--palette auto` chooses a known palette from each `.PCK`/`.ASK` source name;
without a filename hint it keeps the PC-98 ramp. This is a per-file heuristic,
not confirmation of the palette used by a particular screen. `--palette-map`
defines overrides that take precedence over the heuristic. For example,
`"M_CLR": "out/palettes/REPORT.EXE_0138b7.pal"` applies that palette to
`M_CLR.PCK`; you can also use the full source name such as `"M_CLR.PCK"`.
Name matching is case-insensitive.

To compare every saved palette against one file, use `pd2pal_sweep.py`. It
searches the palette directory recursively and writes a separate output folder
for each `.pal` candidate:

```powershell
python pd2pal_sweep.py ..\hdi\PD2D\FACE.PCK out\palettes out\face-sweep
```

For a raw-block `.ASK`, pass `--raw-geom WxH` if the size cannot be inferred.

### `pd2gcp.py` — display lists (`.GCP`, `CHARA.PCK`)

```
python pd2gcp.py (--all DIR | --gcp FILE | --pck FILE [--entry N]) OUTDIR
                 [--pal FILE.pal] [--pal-exe FILE.EXE:0xOFFSET]
                 [--full] [--no-xor] [--dump] [--list] [--scale N] [--base N]
python pd2gcp.py --self-test
```

`.GCP` is not a raster: it is a command stream for the PC-98 **GRCG** (ports
`0x7C`/`0x7E`) whose rows are stored as XOR deltas, and it is finished off by a
row-XOR decode pass. The tool runs the game's loader (`CONVERT.EXE 0x5DE5`), both
players (`0x5FCD` / `0x63E3`) and the pass, and writes the picture. Geometry is in
the block header, so no alignment guessing is involved; `CHARA.PCK`'s 27 display
lists are the 160x240 portraits and PD1's 24 `.GCP` are its full screens.
Full model: [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md).

| option | effect |
|---|---|
| `--all DIR` | every `.GCP` under DIR and every display list in its `.PCK` files |
| `--gcp` / `--pck` | one file / one archive (`--entry N` for a single entry) |
| `--pal FILE.pal` | palette for blocks that carry none (all of PD1's `.GCP`) |
| `--pal-exe FILE.EXE:0xOFFSET` | use one of the 48-byte screen palettes inside an EXE |
| `--full` | keep the declared `width x height` region instead of cropping to the drawn bytes |
| `--no-xor` | stop after the display list — this is the raw row-delta mask |
| `--dump` | also write `<image>.txt`, the decoded command list |
| `--list` | print a table of the blocks found |
| `--self-test` | check the model on hand-built blocks, write nothing |

### `pd2sweep.py` — brute-force palette sweep

Palettes are the one thing that cannot be derived from the files alone: the game
picks a table at run time, and PD1's `.GCP` carry none at all. This tool stops
guessing and renders everything with everything.

```
python pd2sweep.py --data DIR  -o OUTDIR [--mode sheets|full|both] [--cell 160]
                   [--orders engine|all] [--palette-dir DIR]
                   [--images GLOB] [--palettes GLOB] [--max-palettes N] [--list]
python pd2sweep.py --image PD2S.HDI -o OUTDIR          # unpack the disk image first
```

| option | effect |
|---|---|
| `--data DIR` / `--image FILE` | an extracted data tree, or a `.HDI`/`.FDI`/`.fdd`/`.d88` to unpack with `tools/img_extract.py` first |
| `--mode sheets` | **default**: one contact sheet per picture — one cell per palette, labelled, the block's own palette first and marked `*` |
| `--mode full` / `both` | also write one loose PNG per picture and palette (`full/`) |
| `--cell` / `--cols` / `--scale` | sheet cell size, cells per row, upscale for `full` |
| `--orders all` | also try the five other channel permutations of every 48-byte EXE table |
| `--palette-dir DIR` | also sweep every `.pal` under DIR |
| `--images` / `--palettes` | glob filters on picture and palette ids (repeatable) |
| `--max-palettes N` | cap the palettes per sheet (the picture's own palette survives the cap) |
| `--split-bundles` | with `--data`, also unpack every `.IDX`/`.BND` pair (Advanced PD2 keeps the whole game in one bundle). `--image` does this automatically |
| `--list` | report the pictures and palettes it found, write nothing |

It sweeps **every** picture kind it can find (raster `.PCK`/`.ASK` entries, raw
blocks, `.GCP` and `CHARA.PCK` display lists, and the members of an `.IDX`/`.BND`
bundle) against **every** palette it can find (the packed `+0xB` tables of the data
files, every 48-byte table inside the executables via `tools/pal_tables.py`, every
`.pal` you point it at, and the PC-98 default ramp). Output:

```
OUTDIR/palettes/<NNN>_<id>.pal     every distinct palette, JASC
OUTDIR/palettes/index.txt          number -> id, source, hex — the sheet labels use it
OUTDIR/sheets/<picture>.png        the contact sheet
```

A contact sheet beats loose files here: 400 pictures x 60 palettes is a quarter of
a million PNGs, while a sheet is one file per picture and one glance per palette.
Cells are labelled `*N id`, `*` marking the palette the block itself carries.

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

### `pd2bnd.py` — the `.IDX` + `.BND` bundle (Advanced PD2)

Advanced PD2 ships none of the game's data files loose: it ships `PD2DT.BND`
(7.2 MB of concatenated payload) next to `PD2DT.IDX`, its table of contents.

```
python pd2bnd.py --list PD2_3/PD2DT.IDX
python pd2bnd.py --idx PD2_3/PD2DT.IDX --bnd PD2_3/PD2DT.BND -o out/apd2
python pd2bnd.py --auto extracted_dir -o out/bundles
python pd2bnd.py --self-test
```

`.IDX` is a flat array of 24-byte records — `name[16]`, `size` u32, `offset` u32 —
and `.BND` is the raw concatenation they describe. 169 members, no compression, no
padding: `offset[k] + size[k] == offset[k+1]` for every k and the last member ends
exactly on the bundle's last byte, so the table validates itself. The payload is
74 `.PCK`, 39 `.GCP`, 9 `.ASK`, 6 `.SLD` plus drivers, MIDI and the installer's
data — including Advanced-only screens (`SINGLE`, `GAMEOVER`, `M_FAIL`, `AD_END`,
`APD_STF*`, `KOKUPI*`) that no other release has.
Details: [`docs/ADVANCED_PD2.md`](docs/ADVANCED_PD2.md).

### `tools/verify.py` — self-check

Writes nothing; it verifies the claims made in [`docs/FORMAT.md`](docs/FORMAT.md),
[`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.md) and
[`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md):

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
7. `S_ROLL.ASK` is a raw block and its geometry derives as 640x320;
8. every display list (the 26 `.GCP` in the data dir plus 27 `CHARA.PCK` entries)
   reaches its closing `0x7F` exactly when the block runs out of bytes;
9. the geometry in a display-list header for four known blocks (`KOGADO.GCP`
   24x56, `K_BLANC1.GCP` 48x112, `PD2TITLE.GCP` 80x400, `USAGI.GCP` 10x80).

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
| `.GCP` | header + optional **32-byte packed palette** + display list | `9 + hdr[8]` (`0x2B` when the palette is present) | not a raster, but **yes, it renders** — GRCG display list, see `pd2gcp.py` |

Full breakdown: [`docs/FORMAT.md`](docs/FORMAT.md) for the containers and
[`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md) for `.GCP`.

---

## Documentation

| file | contents |
|---|---|
| [`docs/FORMAT.md`](docs/FORMAT.md) | **deep dive:** all containers, the exact codec algorithm, state, bit reader, tokens, the two pitfalls, output layout, proof of correctness |
| [`docs/PALETTE.md`](docs/PALETTE.md) | palette basics: how to choose a screen palette, what the 32-byte `.GCP` ramp is, and how to render with the right colours |
| [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.md) | evidence and details for the 48-byte screen-palette tables inside the EXEs, channel order B,R,G, and how to find/extract them |
| [`docs/ADVANCED_PD2.md`](docs/ADVANCED_PD2.md) | Advanced PD2: the BPB-less `.fdd` layout, the `PD2DT.IDX` + `.BND` bundle (169 members, solved), and why this release is a patch over PD2 |
| [`docs/PD1.md`](docs/PD1.md) | Power Dolls 1: six `.ASK` logos plus 24 `.GCP` display lists — its portraits and screens |
| [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md) | display lists solved: the GRCG model, the loader and both players, the command stream, the row-XOR decode pass, palettes, validation |
| [`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.md) | HDI boot/load chain, `EXEC` map, decoder locations in 15 binaries, how to resolve DGROUP |
| [`docs/PITFALLS.md`](docs/PITFALLS.md) | the traps that derailed earlier investigations (so you do not repeat them) |
| [`docs/LIVE_PALETTE_DUMP.uk.md`](docs/LIVE_PALETTE_DUMP.uk.md) | (Ukrainian) live palette capture from DOSBox-X: the MCP tools (`dosbox_mcp_palette.py`, `mcp_probe.py`, `mcp_poll_palette.py`, `mcp_dump_vram.py`), `pal_from_shot.py`, and the closed "dumper inside the guest" experiment |

Retired tools live in [`_attic-tools/`](_attic-tools/MANIFEST.md) (moved, not
deleted, with per-file reasons and a one-command rollback).

Ukrainian originals: [`README.uk.md`](README.uk.md), `docs/*.uk.md`.

---

## Limitations

* **Palette:** raster entries usually lack a screen palette; without `--pal` or
  `--pal-exe`, the extractor uses the PC-98 default. Display lists are the same
  story: the `.GCP` files carry a 32-byte table but PD1's carry none at all, and
  `CHARA.PCK`'s portraits are drawn with the artwork palette rather than the
  table inside the block. See the palette note above and
  [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md) §6.
* **The compressor** was not recovered; it is in `CONVERT.EXE` (look next to
  the decoder at image `0x54E6`).
* Several archives contain no pictures at all (`MES`, `WMES`, `NAMES`, `MOJI`,
  `NPC`, `MUNIT`, `TUNIT`, `MAP_CHG`, `MISSON*D`, `SCEN_MIS`, `YAOUPD1`,
  `CHARA`, `ANIME`) — they hold text or display lists. Of these, the display
  lists are decoded (`pd2gcp.py`: 27 of `CHARA.PCK`'s 38 entries); the rest is
  still unidentified.

---

## Provenance

Everything was recovered by static analysis (a 16-bit DOS disassembler with
`lcall` resolution and DGROUP-relative string annotation), plus reading GVRAM
out of DOSBox-X save states. The decoder is byte-for-byte identical in 15
binaries (differences are only `lcall` immediates pointing at each build's
runtime), which confirms it is a single statically linked library routine.

The tools do not need the game itself — only its data files.
