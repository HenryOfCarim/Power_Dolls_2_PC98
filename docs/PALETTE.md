> 🌐 **English** · [Українська](PALETTE.uk.md)

# The Power Dolls 2 (PC-98) palette

## 1. The mechanism — proven from the disassembler

The palette writer is at **`BRIEFING.EXE` image `0x10A59`** (the same code
exists in every graphics EXE; in `CONVERT.EXE` it is image `0x5F9B`).

```c
/* arguments: struct (far), x, y, flag */
if (struct[8] >= 0x22 && flag != 0) {
    for (i = 0; i < 16; i++) {
        b0 = es:[bx + 0x0C];        /* bx = pointer to struct + i*2 */
        b1 = es:[bx + 0x0B];
        out(0xA8, b0 >> 4);         /* PALETTE INDEX */
        out(0xAA, b0 & 15);         /* R */
        out(0xAC, b1 >> 4);         /* G */
        out(0xAE, b1 & 15);         /* B */
    }
}
```

The port order is exactly that: **`0xA8` receives the index**, while
`0xAA/0xAC/0xAE` receive the components. This follows from the fact that the
high nibble of the first byte always equals the entry number (`i`), and for the
default palette the resulting triples come out standard: index 1 → blue,
2 → green, 3 → cyan, 4 → red, 7 → white.

### The table format — 32 bytes

```
byte[2i]   = (index << 4) | R
byte[2i+1] =  G << 4      | B
```

Example: the default palette → `00 00 | 0f 00 | f0 00 | ff 00 | 00 f0 | …`

---

## 2. Where that table actually lives

| source | verified | result |
|---|---|---|
| **all 26 `.GCP`, offset `0xB`** | 26/26 valid | 24 hold the default PC-98 palette; **`HARDY.GCP` and `KOGADO.GCP` are custom** |
| `CHARA.PCK` entries, offset `0xB` | 27 entries | all default |

These 32 bytes used to be mistaken for a "constant prologue of the compressed
stream" — they are in fact the palette, which is why it is identical in most
`.GCP` files.

```
$ python pd2pal.py --list ..\hdi\PD2D      # every palette in the entries
$ python pd2pal.py --gcp ..\hdi\PD2D\HARDY.GCP
000 dfb be9 9d6 683 76c ddd bbb 777 555 bfb 7d8 5b6 efb cf7 fff
$ python pd2pal.py --gcp ..\hdi\PD2D\KOGADO.GCP
000 aac eeb 0e0 996 664 429 ddd aaa 666 444 f8c c08 843 632 fff
```

The default palette (from 24 `.GCP` files), which is also what `pd2extract.py`
uses:

```
index :  R G B
  0   :  0 0 0     black
  1   :  0 0 f     blue
  2   :  0 f 0     green
  3   :  0 f f     cyan
  4   :  f 0 0     red
  5   :  f 0 f     magenta
  6   :  f f 0     yellow
  7   :  f f f     white
  8   :  7 7 7     grey
  9   :  0 0 a     dim blue
 10   :  0 a 0     dim green
 11   :  0 a a     dim cyan
 12   :  a 0 0     dim red
 13   :  a 0 a     dim magenta
 14   :  a a 0     dim yellow
 15   :  a a a     dim grey
```

---

## 3. Where the palette is NOT — verified exhaustively

> **Corrected 2026-10-11.** The conclusion drawn below was wrong as a general
> statement, and the reason is instructive: the tables are stored with the
> channels in **(B, R, G)** order — a *cyclic rotation*, which the `rgb`/`grb`/
> `bgr` permutations used here never produce — and the 16 reference colours
> measured from the screenshot were attached to the **wrong indices** (same
> colour set, permuted entries). With the rotation and a fade ladder the live
> palettes match stored tables **16/16**: see
> [`PALETTE_TABLES.md`](PALETTE_TABLES.md) and `tools/pal_tables.py`. The
> rows below remain valid only for the containers and the save state.

| hypothesis | how it was tested | result |
|---|---|---|
| inside `.ASK`/`.PCK` entries | disassembly: the decoder never touches the palette ports | **absent** |
| "48-byte palette at offset 12" | that is the compressed stream — proven by the code, and by those bytes being identical across different images | **not a palette** |
| somewhere in the shipped data as a table | every file, **raw and unpacked** (both containers); the 32-byte packed format in all 4 nibble layouts and with the index in any position; 48-byte RGB/GRB/BGR tables; values as `0..15` and as `n*17`; strict bipartite matching against the 16 colours measured from a real screenshot | **0 matches** — but the search could not have matched: [see the correction](PALETTE_TABLES.md) |
| in a DOSBox-X save state | sections `Vga`, `Render`, `Pic`, `Mixer`, `CPU`, `Memory`; element widths of 2/3/4 bytes and several nibble layouts, same matching | **absent** — the PC-98 palette is hardware state and is not serialised |

**Conclusion (superseded).** The palette of the artwork screens is assembled in
memory at run time from tables the game ships **inside its own EXEs** (48 bytes
per palette, channel order B,R,G, banks every `0x60`/`0xC0` bytes) and is handed
to the palette writer at `BRIEFING.EXE` image `0x10A59`. It therefore *is* in the
files and can be extracted without the emulator — see
[`PALETTE_TABLES.md`](PALETTE_TABLES.md). Dumping from the emulator is now only
needed to learn *which* table a given screen uses.

---

## 4. How to obtain the palette of a specific screen

### Option A — the `.pal` sidecar from DOSBox-X (easiest)

1. In DOSBox-X press **Ctrl+F5** ("Save screenshot").
2. `capture/` will contain `<name>.png` **and `<name>.pal`**.
3. Then:

```powershell
python pd2extract.py --all ..\hdi\PD2D out\png --pal capture\game.pal
```

> A screenshot taken with Windows tooling has no `.pal` — it has to be Ctrl+F5
> inside DOSBox-X.

### Option B — derive it from a screenshot + GVRAM

You need an **unscaled** Ctrl+F5 PNG (exactly 640×400) and a save state from
**the same** screen. The tool aligns the index image with GVRAM and prints the
palette:

```powershell
python pd2pal.py --shot capture\game.png --vram dump\Vga.bin -o out\derived.pal
```

The output includes a `confidence`:
* `≈1.0` — the screens match, the palette is correct;
* `<0.9` — the screenshot and the save state are from different screens; adjust
  the scale/offset (`--sx --sy --ox --oy`) or use another save state.

`Vga.bin` comes out of a `.sav` (which is a ZIP) — unpack the `Vga` member. The
GVRAM mapping is `base = 0x07C000`, plane stride `0x10000`, each plane
400×80 bytes. Ready-made renderer:
`python tools\render_vram.py dump\Vga.bin out\screen.png`.

### Option C — supply your own palette

`--pal` accepts any of: JASC-PAL, raw 768 bytes (256×RGB), 48 bytes
(16×RGB, values 0–15), or text with 16 lines of `R G B`.

```powershell
python pd2pal.py --default -o out\pc98default.pal      # JASC-PAL
python pd2pal.py --default --fmt nibbles -o out\d.nib  # 48 raw bytes
```

---

## 5. What you can do right now

`pd2extract.py` uses the **real default PC-98 palette** (taken from the `.GCP`
files) by default. For `.GCP` screens that carry a custom palette (`HARDY`,
`KOGADO`) the exact colours come out immediately:

```powershell
python pd2pal.py --gcp ..\hdi\PD2D\HARDY.GCP -o out\hardy.pal
python pd2extract.py --all ..\hdi\PD2D out\png --pal out\hardy.pal
```

The geometry of the extracted images is always correct — only the colours depend
on the palette. That is also why `--palette gray` is useful: on a greyscale ramp
the structure is clearly visible while the palette is still unknown.
