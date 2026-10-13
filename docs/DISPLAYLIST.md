> 🌐 **English** · [Українська](DISPLAYLIST.uk.md)

# `.GCP` / `CHARA.PCK` display lists — solved

The display lists are **decoded**. Every shipped block runs to its last byte and
renders as a picture; `pd2gcp.py` is the extractor.

| | |
|---|---|
| `.GCP` (PD1: 24 files, PD2: 26 files) | ✅ rendered as PNG |
| `CHARA.PCK` (27 of 38 entries) | ✅ rendered as PNG |
| Stream grammar | ✅ recovered, byte-exact (`used == len(stream)` on all 77 blocks) |
| Palettes | ✅ 32-byte packed table at `+0xB`; PD1's `.GCP` carry none (they use EXE tables) |
| `CHARA.PCK` entries 27..37 | data, not display lists — they are still unconverted |
| The Huffman branch of the byte reader | code present, **dead for this data** (see §7) |

```
python pd2gcp.py --gcp hdi/PD2D/KOGADO.GCP out
python pd2gcp.py --pck hdi/PD2D/CHARA.PCK out --entry 0
python pd2gcp.py --all hdi/PD2D out
python pd2gcp.py --all "power dolls 1/_unpacked" out --pal-exe "power dolls 1/_unpacked/PREMIUM.EXE:0xEDF1:G,R,B"
```

![Power Dolls 2 title screen, rendered from PD2TITLE.GCP](img/gcp_pd2title.png)

## 1. What a block is

```
+0      flags
          bit 0x40  the stream is stored verbatim
          bit 0x80  GRCG read-modify-write (XOR) tile mode
          bits 0x30 0 = plain draw; else the row fill runs and the row-XOR
                    decode pass is applied (flags & 0x30) >> 4 times
          bits 0x0F GRCG plane mask: a SET bit means the plane is NOT written,
                    so the stream carries tile bytes only for the planes whose
                    bit is clear
+1      width  in bytes - the row extent of the fill and of the XOR pass
+2..3   height in rows (16-bit little endian)
+4..7   the GRCG seed tile: one byte per written plane, in B,R,G,E order
+8      payload offset counted from +9; >= 0x22 means "the 32-byte palette is
        at +0xB and the stream starts after it"
+9..10  a 16-bit VRAM offset; the loader uses it instead of the caller's pen
        when the caller passes a pen >= 0x7D00
+0xB..  the 16-colour packed palette when +8 >= 0x22:
        byte[2i] = (index << 4) | G,  byte[2i+1] = (R << 4) | B
stream  block + 9 + block[8]
```

`width x 8` is the picture width in pixels and `height` its height: `CHARA.PCK`
entries are `20 x 240` = **160x240 portraits**, `KOGADO.GCP` is `24 x 56`,
`PD2TITLE.GCP` is `80 x 400` = a full screen. No guessing, no alignment search -
the geometry is in the header.

## 2. The loader — `CONVERT.EXE` image `0x5DE5`

```c
void gcp_load(struct block *b, unsigned pen, int load_palette) {
    unsigned mask  = ~b->flags & 0x0F;       /* planes that ARE written */
    unsigned value = b->flags;               /* header byte, see below  */
    unsigned width = b->width, height = b->height;

    if (b->payload >= 2 && pen >= 0x7D00)    /* the block overrides the pen */
        pen = b->vram_offset;

    out(0x7C, (b->flags & 0x0F) | 0x80);     /* GRCG on, plane mask        */
    for (i = 0; i < 4; i++)                  /* seed the GRCG tile         */
        out(0x7E, (mask & (1 << i)) ? b->tile[read++] : 0);

    if (b->flags & 0x30)                     /* clear/fill every row       */
        for (r = 0; r < height; r++)
            fill(0xA800, pen + r * 0x50, b->width, 0);   /* writes the tile */

    player(b, pen, popcount(mask));          /* §4: the command stream     */

    n = (b->flags & 0x30) >> 4;              /* §5: the row-XOR decode     */
    while (n--)
        for (r = 0; r < height - 1; r++)
            for (p = 0; p < 4; p++)
                if (mask & (1 << p))
                    xor_row(0xA800 + p * 0x800, pen + r * 0x50, b->width);

    if (b->payload >= 0x22 && load_palette)  /* 16 colours from ports      */
        for (i = 0; i < 16; i++) { ... out(0xA8/0xAA/0xAC/0xAE, nibbles); }
}
```

`xor_row(seg, off, n)` is `plane[off + 0x50 .. +n] ^= plane[off .. +n]` — it folds
one 80-byte VRAM row into the next.

Two players exist and are chosen by the header byte:

| player | image | used when |
|---|---|---|
| A | `0x5FCD` | `(flags & 0x70) != 0x40` |
| B | `0x63E3` | `(flags & 0x70) == 0x40` |

They differ only in how they fetch stream bytes: player A goes through the byte
reader at `0x6213`, player B reads the block directly. Because flag `0x40` is set
in **every** shipped block (and the byte reader returns bytes verbatim whenever
that flag is set), both players behave identically on this data.

Player positions: PD2 `CONVERT.EXE 0x5FCD`, `STARTUP.EXE 0x608F`,
`TACTICS.EXE 0xC33F`, `BRIEFING.EXE 0x10AA1`, `OPENING.EXE 0x5D90`,
`REPORT.EXE 0x802B`, `CHOICE.EXE 0x670C`, `PD2SHELL.EXE 0x5AF0`;
PD1 `PREMIUM.EXE 0x63E8`, `STARTUP.EXE 0x5230`. (`MAKEINIT.EXE` and `GO.EXE` are
different builds and do not contain it.)

## 3. Why ports `0x7C` / `0x7E`

Those two ports are the PC-98 **GRCG** (Graphic Charger), not the µPD7220:

* `0x7C` — mode register: bit 7 enables the GRCG, bit 6 selects the
  read-modify-write mode, bits 0..3 are the plane mask, and a **set** bit means
  *no access* to that plane. That is why the stream carries tile bytes only for
  the planes whose bit is **clear** (`mask = ~flags & 0x0F`).
* `0x7E` — the four tile registers, written one byte per plane in **B, R, G, E**
  order (the same order the raster codec uses).

Once the GRCG is on, **the byte the CPU stores into GVRAM is irrelevant**: the
hardware replaces it with the tile. So `stosb` is used purely as a *trigger* that
stamps eight pixels, and the value the game writes into it is a don't-care (in
XOR mode it is the OR of the differences between the incoming tile and the seed
tile - a "did anything change" flag). This one fact explains why the earlier
model, which read those `stosb` values as colours, could never match VRAM.

## 4. The command stream

The stream starts with one tile (one byte per written plane, four for a normal
picture). Then, until the second `0x7F`:

| byte | meaning |
|---|---|
| `< 0x7D` | `skip = (c << 8) \| next`, then stamp one byte |
| `0x80..0xFD` | `skip = c - 0x80`, then stamp one byte |
| `0x7D` | `count = ((d << 8) \| next) + 2`, or `(d - 0x80) + 2` when `d >= 0x80`; stamp the current tile `count` times |
| `0x7E` | pen = base, and read a fresh tile |
| `0x7F` | pen = base; the first one switches to the second pass, the second one ends the block |

A **stamp** writes the current tile at the current VRAM offset - one byte per
written plane, eight pixels - and advances the offset by one. The offset is a
plain byte offset into a VRAM plane, so a screen row is 80 bytes and a skip of
`0x50` moves down exactly one row.

In the second pass every stamp first pulls a fresh tile from the stream, so the
stream naturally splits into "a few tiles stamped in long runs" and "a bitmap".

`0x7F` is also what makes the model checkable: the player must hit the closing
`0x7F` exactly when the block runs out of bytes. All **77** shipped blocks do -
the same "consumed to the last byte" argument that validates the raster codec.

## 5. The row-XOR pass: the stream is a row *delta* image

Stop after §4 and the picture looks like coloured line art:
[dithered outlines only](img/gcp_delta_vs_xor.png) (left). That is not the art -
it is the encoding.

The artist stored each row as the **XOR difference** from the row above, and the
loader integrates it back:

```c
for (r = 0; r < height - 1; r++)
    plane[pen + (r+1)*0x50 ..][0 .. width] ^= plane[pen + r*0x50 ..][0 .. width];
```

run `(flags & 0x30) >> 4` times - once for the plain screens (`0x50`), twice for
the ones that also play the dissolve (`0x60`). After the pass the same block is a
full illustration:

![the same block after the row-XOR pass](img/gcp_chara0.png)

This also explains the earlier finding that "`.GCP` carry no palette" on PD1:
they do not need one to store the *mask*, and the screens' colours come from the
48-byte tables inside the EXEs (`pd2pal.py --exe`, `docs/PALETTE_TABLES.md`).

## 6. Palettes

The 32-byte table at `+0xB` is the engine's packed form
(`byte[2i] = (index << 4) | G`, `byte[2i+1] = (R << 4) | B` — the three colour
ports are `0xAA` = green, `0xAC` = red, `0xAE` = blue, see
[`PALETTE.md`](PALETTE.md) §1). It is
self-describing: the high nibble of the second byte is the index it belongs to, so
`pd2pal.palette_from_packed()` rejects anything that is not one of these tables.

Carrying a table is not the same as *being drawn with* it, and the two cases
differ:

* **PD1 `.GCP`** have `+8 == 0`, i.e. no table at all. The screens' colours come
  from the 48-byte banks inside the EXEs; `--pal-exe PREMIUM.EXE:0xEDF1:G,R,B` is
  a good starting point for the portraits (the `:G,R,B` is PD1's byte order - see
  [`PALETTE.md`](PALETTE.md) §1).
* **PD2 `.GCP`** carry a table and most of them carry the default ramp
  (`HARDY.GCP`, `KOGADO.GCP` are the two custom ones). The embedded table is what
  `pd2gcp.py` uses by default.
* **`CHARA.PCK`** entries carry the *default ramp* at `+0xB`, but the portrait
  screens are drawn with the shared artwork palette
  (`BRIEFING.EXE 0x234C6`). Compare:

  ```
  python pd2gcp.py --pck hdi/PD2D/CHARA.PCK out --entry 0
  python pd2gcp.py --pck hdi/PD2D/CHARA.PCK out --entry 0 --pal-exe hdi/PD2D/BRIEFING.EXE:0x234C6
  ```

  The first run gives a plainly-coloured portrait, the second the artwork.

The captions of the images above use the artwork palette for `CHARA.PCK` and the
file's own table elsewhere. `pd2pal.py --suggest` ranks the candidates for a
given asset; see [`PALETTE.md`](PALETTE.md) and [`PALETTE_TABLES.md`](PALETTE_TABLES.md).

Rather than reason about which table belongs to which screen, sweep it:
`pd2sweep.py` renders every picture it can find with every palette it can find
and writes one labelled contact sheet per picture — 26 `.GCP` and 27 `CHARA.PCK`
blocks against the whole EXE bank is 33 sheets for the HDI data.

```
python pd2sweep.py --data hdi/PD2D -o out/sweep
python pd2sweep.py --data hdi/PD2D -o out/sweep --orders all   # all channel permutations too
```

## 7. The dead Huffman branch

The byte reader at `0x6213` has two modes. When flag `0x40` is set it returns the
next byte from the block (`lodsb`); otherwise it walks a 256-symbol Huffman tree
that a recursive builder at `0x6306` reads out of the stream
(`1` = internal node, recurse twice; `0` = leaf, take the next 8 bits).

That builder stores its `1`-children at `DGROUP:0x955E` and its `0`-children at
`DGROUP:0x935E`, while the reader looks its `1`-children up at `DGROUP:0x915E`.
The `0x915E` table is BSS and is written by nothing in any shipped build (all
three `CONVERT.EXE` copies agree), so the compressed path would decode every
`1`-branch as symbol 0. No shipped `.GCP` or `CHARA.PCK` entry reaches it: every
one of them sets flag `0x40`. The branch is dead code, and this is why the
earlier `0x7D/0x7E/0x7F` "grammar" could be read straight off the raw bytes.

## 8. Validation

* **Structural.** All 77 display lists (24 PD1 `.GCP`, 26 PD2 `.GCP`, 27
  `CHARA.PCK` entries) consume their stream down to the closing `0x7F`;
  `tools/verify.py` checks [8] and [9] enforce it, plus the header geometry of
  four blocks.
* **Content.** The output is not noise: `PD2TITLE.GCP` is the title screen with
  its menu, `SPRE00.GCP` is the epilogue text screen (shown as a text raster with
  correctly shaped kana), `CHARA.PCK` entries are the 160x240 portraits, and
  `ELIOLA.GCP` is a full illustration whose character name is legible.
* **Independent path.** `K_BLANC1.GCP`, `KOGADO.GCP` and `PLAN_GB/GC.GCP` have
  `flags & 0x30 == 0`, so they exercise the player *without* the XOR pass; the
  full-screen `SPRE00.GCP` renders correctly that way.
* **Palette.** The 32-byte packed tables decode to the same 16 colours the
  palette writer feeds to ports `0xA8/0xAA/0xAC/0xAE`, which is what
  `pd2pal.py` already validated against live dumps.

## 9. Leftovers

* `CHARA.PCK` entries 27..37 are not display lists (11 entries). They do not
  end with `0x7F` and do not decode; their role is still open.
* `ANIME.PCK`, `EVENT.PCK`, `INIT.PCK`, `MAP_CHG.PCK`, `MES.PCK`, `MOJI.PCK`,
  `NPC.PCK`, `MUNIT.PCK`, `TUNIT.PCK`, `NAMES.PCK`, `SCORE_N/SCORE_P.PCK`,
  `OP_*.PCK`, `YAOUPD1.PCK`, the `MISSON*.PCK` set: not rasters, not display
  lists either. Text, tables and yet-unidentified data.
* PD1's `.GCP` palettes are still matched by hand (`--pal-exe`); the game picks
  one of the 40 tables in `PREMIUM.EXE` per screen at run time.
