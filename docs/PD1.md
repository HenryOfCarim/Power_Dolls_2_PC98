> 🌐 **English** · [Українська](PD1.uk.md)

# Power Dolls 1 (S-Premium Disc) — where the graphics live

## 1. Short answer: 6 PNGs is not a bug

The disc really does hold only **six raster pictures**, and all of them are small
logos:

| file | size | picture |
|---|---|---|
| `KGD.ASK` | 1330 B | 192×56 (the KOGADO logo) |
| `DETA.ASK` | 1021 B | 200×76 |
| `SERV.ASK` | 745 B | 136×72 |
| `LIM.ASK` | 659 B | 128×72 |
| `LINE.ASK` | 445 B | 88×72 |
| `OF.ASK` | 228 B | 48×60 |

Everything else is **24 `.GCP` files** of 8–95 KB named after characters
(`ELIOLA`, `JULLY`, `MARRY`, `MELL`, `RISSA`, `SELMA`, `HUANG`, `MARGA`,
`CHARA04…CHARA20`, `PD_LOGO`, `PL00`, `SPRE00…SPRE04`). Those are the "missing"
portraits and screens.

## 2. Why they do not convert: they are display lists, not rasters

PD1's `.GCP` format is **the same GDC command stream** that PD2 keeps in
`CHARA.PCK` and in its own `.GCP` files. Evidence:

| property | PD1 `.GCP` | PD2 `CHARA.PCK` |
|---|---|---|
| head | `50 14 f0 00` (6 files), `60 14 f0 00` (2) | `60 14 f0 00` (20 entries), `50 14 f0 00` (7) |
| "screen" head type | `60 50 90 01` (10), `40 50 90 01` (6) | the same first 4 bytes in `.GCP` (e.g. `BUSOU_B.GCP`) |
| terminator | **all 24** end with byte `7f` | 27 of 38 end with `7f` |
| byte histogram | dominated by `00 80 01 81 7e 02 …` | the same picture |
| length parity | 11 odd, 13 even | — |
| palette inside | **none**, in any encoding | yes (32 bytes at `0xB`) |

The last two rows are what rules out a raster: a real 4-plane bitmap has an even
length `w*h/2`, and no palette is stored in these streams at all.

## 3. So where do the 40 palettes come from

From the **EXEs**: 37 tables in `PREMIUM.EXE` and 6 in `STARTUP.EXE` (40 distinct
after deduplication). That is the same "bank of screen palettes" pattern as in
PD2: the code picks a table and hands it to the palette writer. So "many palettes,
little raster" is the expected picture — the palettes exist, the pictures are
drawn by display lists.

Consequence for any render: the pictures carry no palette, so the extractor falls
back to the `.GCP` default ramp and the colours are wrong even though the geometry
is right — see the "read first" section of [`PALETTE.md`](PALETTE.md).

## 4. What this means for PD2

The same blocker applies to PD2: the extractor still reports `CHARA.PCK`,
`ANIME.PCK`, `EVENT.PCK` and `MAP_CHG.PCK` as "0 image entries". One display-list
decoder therefore unlocks, at once:

* Power Dolls 1's portraits and screens (24 `.GCP`);
* Power Dolls 2's characters, animation and events (`CHARA`/`ANIME`/`EVENT`).

## 5. Next steps

1. **Static.** PD2's display-list handler is documented: `CONVERT.EXE` image
   `0x5CE2` (it writes ports `0x7C`/`0x7E`). PD1's equivalent lives in
   `PREMIUM.EXE`/`STARTUP.EXE` (same library). Disassemble it and recover the
   command set; the byte histogram (`80`/`00`, `81`/`01`, `7e`) hints at a byte
   stream with a flag bit in the high bit.
2. **Dynamic (ground truth).** Take a DOSBox-X save state on a portrait screen —
   the VRAM then gives the byte-exact expected result, i.e. a known-answer pair to
   validate the decoder against (exactly how the LZSS codec was cracked). VRAM
   rendering already exists: `tools/render_vram.py`.
