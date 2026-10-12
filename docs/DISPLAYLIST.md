> 🌐 **English** · [Українська](DISPLAYLIST.uk.md)

# `.GCP` / `CHARA.PCK` display lists — reverse-engineering status

## 1. The player is found, and it is shared by both games

The display-list player is **`CONVERT.EXE` image `0x5FCD`** (prologue `enter 8,0`).
Its body is byte-identical in **10 of 15** binaries checked, across both games:

| binary | routine start |
|---|---|
| PD2 `CONVERT.EXE` | `0x5FCD` |
| PD2 `STARTUP.EXE` | `0x608F` |
| PD2 `TACTICS.EXE` | `0xC33F` |
| PD2 `BRIEFING.EXE` | `0x10AA1` |
| PD2 `OPENING.EXE` | `0x5D90` |
| PD2 `REPORT.EXE` | `0x802B` |
| PD2 `CHOICE.EXE` | `0x670C` |
| PD2 `PD2SHELL.EXE` | `0x5AF0` |
| **PD1 `PREMIUM.EXE`** | `0x63E8` |
| **PD1 `STARTUP.EXE`** | `0x5230` |

(`MAKEINIT.EXE`, `GO.EXE` are different builds and do not contain it.)

Disassembly listings: `_dec/gcp_player_convert.asm`, `_dec/gcp_player_premium.asm`
(`python _dec\dis_gcp.py FILE.EXE 0x5FCD 0x6213 --follow 600`).

## 2. Block structure

```
+0..3    type:  60 14 f0 00 | 50 14 f0 00 | 60 50 90 01 | 40 50 90 01
+4..7    00 00 00 00
+8       payload offset: 0x22 in PD2's CHARA (data from +0x2B, i.e. right after the
         32-byte palette at +0xB), 0x00 in PD1's .GCP (data from +9)
+9..     the stream
```
The player sets its read pointer to `block + (block[8] + 9)`; byte `block[0]`
(e.g. `0x60`) is only the "read straight from memory" flag (bit `0x40`).

All 24 of PD1's `.GCP` and 27 of the 38 `CHARA.PCK` entries **end with byte
`0x7F`** — the end of the stream.

## 3. Arguments

Called from `0x5EE5` with `(far pointer to the block, VRAM plane offset, a header
byte)`. The plane offset is the pen's "home" that `0x7F` resets to; the header byte
is passed to the helper as the number of bytes per 8-pixel group.

## 4. Stream grammar (from the code)

| byte | action |
|---|---|
| `< 0x80` | pen += `(c << 8) \| next_byte`, then write the current value |
| `0x80..0xFC` | pen += `c - 0x80`, then write the current value |
| `0x7D` | repeat the current value `count + 2` times; `count` is coded the same way (1 or 2 bytes) |
| `0x7E` | new value: the helper reads `N` bytes and pushes them to the GDC |
| `0x7F` | reset the pen to "home" (end of stream when it is the last byte) |

The helper (image `0x613E`) drives the GDC ports:
* `0x7C ← 0x80 | plane_mask` — copy mode;
* `0x7C ← 0xC0 | plane_mask` — XOR mode (then it returns the OR of the differences);
* `0x7E ← 4 bytes` (the four planes of one 8-pixel group);
* after the end of the stream — `0x7C ← 0`.

## 5. What is already proven statistically

* `0x7F` resets land on **VRAM row starts** (`offset % 80 == 0`): 20 of 26 in
  `ELIOLA.GCP`, 15 of 19 in `CHARA#2` — so the pen walks rows of 80 bytes
  (640 pixels);
* PD1's `.GCP` carry no palette (every encoding checked) and no LZSS stream (32- or
  16-bit size field), so they really are command streams;
* the 4-plane structure is visible in the code itself: the helper always hands the
  GDC exactly four bytes per group, and the plane mask decides which of them are
  written and which become zero.

## 6. What is left (and how one capture closes it)

The value semantics and the row/plane structure are now recovered (section 7); what
was missing earlier is that a block is not one picture but a stack of plane masks,
so aligning "value 0..15 against one plane" could never match. The remaining work is
mechanical: implement the bit-level layer alignment against the captured planes.

## 7. Refined model (disassembly of the loader and the second player)

There are **two** players; the block's header byte decides which (`& 0x70`):

* `0x5FCD` — when `(header & 0x70) != 0x40`;
* `0x63E3` — when `(header & 0x70) == 0x40` (all the screen `.GCP`, e.g. `SPRE00.GCP`;
  listing: `_dec/gcp_player2_convert.asm`).

The `0x63E3` player reads unambiguously:

```
DL = the value (an argument, CONSTANT for the whole block)
DI = the plane offset (an argument)
the stream starts at block + block[8] + 9
  < 0x7D  : skip = (c << 8) | next ; one write
  >= 0x80 : skip = c - 0x80        ; one write
  0x7D    : count = ((d << 8) | next) + 2 ; write the value that many times
  0x7E    : reset the pen to DI
  0x7F    : end of segment (return)
```

And the **loader** (`0x5EFC`) drives it like this:

```
for each row (stride 0x50 = 80 bytes, one VRAM row):
    si = base + row*0x50
    if mask bit 1 -> 0x6388(0xA800, si, value)   /* plane B */
    if bit 2      -> 0x6388(0xB000, si, value)   /* R */
    if bit 4      -> 0x6388(0xB800, si, value)   /* G */
    if bit 8      -> 0x6388(0xE000, si, value)   /* E */
```

So a `.GCP` picture is a **stack of layers**: each layer has a plane mask, a constant
value byte, a height in rows and a per-row "skip then write" list (`0x7F` closes one
row/plane segment). It is not one bitmap in the stream but **per-plane bit masks**
that compose an indexed image.

The helper `0x6486` (for the `0x63E3` player) drives the GDC: `0x7C ← 0x80 | (flags & 0xF)`
(plus `0xC0` for XOR when bit `0x80` is set), then four bytes to `0x7E`, where a
plane's byte comes from the stream only if the matching mask bit is **clear**.

Consequence for alignment: compare **bits** (layers are plane masks) and mind the
`0x50` row stride. The first aligner did neither, hence zero real matches.

## 8. What has already been captured from the emulator

`_dbg\vram_dumper.bat` produced 21 frames from the game (title, biographies,
posters and **mid-transition frames**): `pd2gfx/out/vram/pd1/`. For example
`pd1_012_172051/preview.png` shows two posters blended through a checkerboard mask.

## 8a. Important correction: PD1's `.GCP` are NOT pictures

The disassembly shows the routines around `.GCP` in `CONVERT.EXE` are a
**transition/wipe engine**:

* `0x6388` — `xor_row(ds, bx, cx)`: `si = 0x50` and `[bx+si] ^= [bx]`, i.e. **XOR one
  VRAM row into the next** (across the selected planes);
* `0x63BD` — a fast `memset` (`rep stosw`) filling part of a plane;
* the loader `0x5DE5` takes the plane mask (`~block[0] & 0x0F`), the **value**
  `block[1]` (in PD1 `0x50`/`0x14` — the classic 50 %/25 % dither patterns) and the
  height `u16@+2`, draws the mask with the player (`0x5FCD`/`0x63E3`), then runs the
  XOR row dissolve.

In other words, PD1's `.GCP` describe **how to reveal a picture that is already
there** (dither + XOR); they do not contain pixels. The captured frames show it: in
`pd1_012_172051` two posters are mixed by the checkerboard mask.

So PD1's "only 6 pictures" is not an anomaly: the six `.ASK` are logos, and the
character posters are stored **compressed** elsewhere. A "verbatim in VRAM" scan over
29 files (with 68,505 informative 24-byte windows, i.e. no degenerate zero windows)
found no match at all, confirming the data is compressed. Next step: run the known
LZSS codec over `PREMIUM.EXE`, `STARTUP.EXE`, `LAGDISK1.EXE`, `LAMAIN.BIN`,
`LALOCAL.BIN`, `LAEND.BIN`, `ALLOGO.BIN` and compare the output with the 21 captured
frames (the reference already exists).

## 9. Capturing the ground truth (ready to run)

```powershell
_dbg\run_vram_dump.bat            # PD1 (default)
_dbg\run_vram_dump.bat pd2        # PD2 dash HDI
```

The script starts `tools/mcp_dump_vram.py`, then launches the game with
`mcp_server`. Every 4 s the dumper freezes the guest, pulls the four planes through
the debugger (`B.bin`, `R.bin`, `G.bin`, `E.bin` from segments
`A800`/`B000`/`B800`/`E000`) plus the palette (`PC98 DACPAL`), and saves each
**distinct** screen under `pd2gfx/out/vram/<version>/<frame>/` with a 640x400
`preview.png`.

Verified against the live emulator: DOSBox-X connects, `MEMDUMPBIN` delivers the
planes, the palette parses, previews are written (the files land in the project
folder — DOSBox-X writes them relative to its working directory, and paths with
spaces and parentheses do not break it).

Then align the stream with the real planes:

```powershell
python _dec\align_displaylist.py "pd2gfx\out\vram\pd1\pd1_000_HHMMSS" --data "power dolls 1\_unpacked"
```

The tool votes for the draw offset `D` (rare values vote first) and then re-checks
the full match rate. Control on synthetic data: `D=0`, 400 votes against 7,
**100%** match.
