> 🌐 **English** · [Українська](PD1.uk.md)

# Power Dolls 1 (S-Premium Disc) — where the graphics live

## 1. Short answer

The disc holds six raster pictures (`.ASK`, all of them small logos) and **24
`.GCP` display lists** of 8–95 KB named after characters (`ELIOLA`, `JULLY`,
`MARRY`, `MELL`, `RISSA`, `SELMA`, `HUANG`, `MARGA`, `CHARA04…CHARA20`,
`PD_LOGO`, `PL00`, `SPRE00…SPRE04`).

`.GCP` is not a raster but it is **not lost data either**: it is the same display
list format PD2 keeps in `CHARA.PCK`, it is decoded now, and all 24 files convert
to PNG:

```
python pd2gcp.py --all "power dolls 1/_unpacked" out --pal-exe "power dolls 1/_unpacked/PREMIUM.EXE:0xEDF1:G,R,B"
```

Eight of them are 160x240 character portraits (`CHARA04…CHARA20`), sixteen are
full 640x400 screens. `ELIOLA.GCP` is a complete illustration and the
`SPRE00…SPRE04` set is the epilogue text screens.

## 2. What they are, precisely

[`DISPLAYLIST.md`](DISPLAYLIST.md) has the full model. In one line: a `.GCP` is a
GRCG tile stream whose rows are stored as XOR deltas, and the loader at
`CONVERT.EXE 0x5DE5` paints it and then integrates the rows.

| property | PD1 `.GCP` | PD2 `CHARA.PCK` |
|---|---|---|
| head | `50 14 f0 00` (6 files), `60 14 f0 00` (2) | `60 14 f0 00` (20 entries), `50 14 f0 00` (7) |
| "screen" head type | `60 50 90 01` (10), `40 50 90 01` (6) | the same first 4 bytes in its own `.GCP` |
| terminator | **all 24** end with `7f` | 27 of 38 end with `7f` |
| geometry in the header | yes: e.g. `20 x 240`, `80 x 400` | yes: `20 x 240` |
| palette inside | **none** in any encoding | 32 bytes at `0xB` (the default ramp) |
| rendered | ✅ `pd2gcp.py` | ✅ `pd2gcp.py` |

The `0x7D / 0x7E / 0x7F` bytes that earlier looked like a puzzle are the command
grammar, and the byte histogram (`00 80 01 81 7e 02 …`) is the skip/write pattern
of a bitmap, which is exactly what it turned out to be.

## 3. So where do the 40 palettes come from

From the **EXEs**: 37 tables in `PREMIUM.EXE` and 6 in `STARTUP.EXE` (40 distinct
after deduplication). That is the same "bank of screen palettes" pattern as in
PD2: the code picks a table and hands it to the palette writer. PD1's `.GCP`
carry no palette at all, so a render needs `--pal` / `--pal-exe`:

```
python pd2gcp.py --gcp "power dolls 1/_unpacked/CHARA04.GCP" out \
                 --pal-exe "power dolls 1/_unpacked/PREMIUM.EXE:0xEDF1:G,R,B"
```

`0xEDF1` is the artwork palette (skin tones first); `pd2pal_sweep.py` and
`pd2pal.py --suggest` help to pick another one.

**The `:G,R,B` suffix matters.** PD1's executables store their 48-byte tables in a
different byte order from PD2's: the palettes captured from the running game match
PD1's tables only when an entry is read as `(byte[3i+1], byte[3i+0], byte[3i+2])` —
11 of the 20 frames dumped from DOSBox-X match a PREMIUM table that way and none
match the other order, which is why the default (`B,R,G`, correct for PD2) turns
PD1 portraits magenta and green. `tools/verify.py --pd1` pins it: `PREMIUM.EXE
0xEDF1` and PD2's `STARTUP.EXE 0x9311` are the same 16 colours with the first and
third bytes exchanged, so each game needs its own reading. See
[`PALETTE.md`](PALETTE.md) §2.

## 4. What this means for PD2

The same decoder covers PD2: `CHARA.PCK`'s 27 display lists are the 160x240
portraits, and PD2's own `.GCP` files are the title screen, the background plates
(`KABE*`, `K_BLANC*`), the score and planning panels and the Kogado logo.

It does **not** cover everything: `ANIME.PCK`, `EVENT.PCK`, `INIT.PCK`,
`MAP_CHG.PCK`, `MES.PCK`, `MOJI.PCK`, `NPC.PCK`, `MUNIT.PCK`, `TUNIT.PCK`,
`NAMES.PCK`, `SCORE_N/SCORE_P.PCK`, `OP_*.PCK`, `YAOUPD1.PCK` and the
`MISSON*.PCK` set are neither rasters nor display lists — they hold text, tables
and data that is still unidentified. See the tail of
[`DISPLAYLIST.md`](DISPLAYLIST.md).

## 5. What is still open

1. **The per-screen palette.** PD1 ships 40 tables and picks one at run time; the
   extractor takes whatever `--pal-exe` is given. Matching each `.GCP` to its
   screen palette (the way `docs/PALETTE_TABLES.md` did for PD2) would make the
   PD1 set convert with no arguments.
2. **PD1's `.GCP` that are not portraits or screens.** `JI.GCP` is the smallest
   full-screen block (8 KB); blocks like it are likely overlays drawn on top of
   something already in VRAM. `pd2gcp.py --no-xor` shows the raw row-delta mask,
   which is the right input for that kind of overlay work.
