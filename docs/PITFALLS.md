> 🌐 **English** · [Українська](PITFALLS.uk.md)

# Pitfalls — what derailed earlier investigations

This file is distilled experience. Every item below costs time and produces
wrong results if you do not know about it in advance.

---

## 1. The "48-byte palette at offset 12" is the compressed stream

The longest-running trap. An entry has a 12-byte header and then the compressed
stream immediately follows. Investigators took the first 48 bytes of the stream
for a 16-colour RGB palette and started decoding at offset 60.

Why it looks convincing:

* 48 = 16 × 3 — "exactly a palette";
* those bytes are **identical across different images of the same family** — a
  "shared palette";
* running VRAM indices through that table yields a **recognisable picture** —
  because the geometry comes from the indices, not from the palette.

How to spot it: a real palette cannot be byte-for-byte identical across 38
different faces. The start of a compressed stream for similar pictures can.

**Consequence:** every sweep that started at offset 60 was doomed.

---

## 2. The "known-answer pairs" were mismatched across builds

The main reason a correct codec could not be confirmed.

Verified: `_ref/entry_NN_stored.bin` is the **root (floppy) `FACE.PCK`**, 36/36
matches. But the `_portrait/*` VRAM captures come from a different build (HDI).
So different pictures were being compared, and no correct decoder could ever
reach 100 %.

**Lesson:** before building a known-answer test, make sure the input and the
output come from **the same** build of the game. It is trivial to check:

```python
assert open("_ref/entry_00_stored.bin","rb").read() == floppy_entry_0
```

---

## 3. The output order is not "four consecutive planes"

The expectation was `plane B`, `plane R`, `plane G`, `plane E` — four blocks of
`w/8*h` bytes each. In reality the output is **interleaved**: 4 bytes per group
of 8 pixels.

Because of this:

* searching RAM for "the decoder's output" using a ready 4608-byte template
  could never work;
* comparing against GVRAM "plane by plane" produced accidental matches.

---

## 4. LZSS pads itself — "it produced the right length" is NOT proof

The classic trap. LZSS can emit any requested number of bytes from an empty
ring, so the test "the output is exactly `decoded_size`" **passes with wrong
parameters**.

Measured: **360/360 entries "pass" that test for 40 different parameter sets**,
including ones with the wrong bit order, offset and length.

Reliable criteria:

| criterion | why it works |
|---|---|
| **visual legibility** | a random decode does not produce readable text |
| **exact match against GVRAM** | requires the same build (see pitfall 2) |
| **consuming the stream to the last byte** | strong, but not absolute — combine with the others |
| **output structure** | 20–78 % zeros and uniform runs thousands of bytes long; for noise 0.3 % and a maximum of 2 |

Useful corollary: a correct decode leaves exactly **1 byte** of the stream
unused (the bit-buffer tail). That holds on all 360 entries.

---

## 5. "The offset is relative" and "the length is +2" — two deviations from canonical LZSS

* The match offset is an **absolute ring index**, not a distance back from
  `wpos`. The formula `ring[(wpos - offset) & mask]` yields garbage.
* The assembly says `add ax,2`, but the loop is tested as `cmp len,i / jge`, so
  the body runs for `i = 0 … len` inclusive. The real length is
  `(c2 & 0x0F) + 3`.

Both deviations give "almost right" — the output looks like data but does not
match. That is exactly why sweeps over the canonical variants failed.

---

## 6. `.GCP` is not a picture

`CHARA.PCK`, `ANIME.PCK`, `MES.PCK`, `INIT.PCK`, `MAP_CHG.PCK`, `MISSON*D.PCK`
and others share **the same 12-byte prefix** as pictures and are easily mistaken
for rasters. In fact they are display lists for the hardware GDC (handler
`CONVERT.EXE` image `0x5CE2`, writing to ports `0x7C`/`0x7E`).

The distinguishing sign: `decoded_size == w*h/2` does not hold. That test (plus
`width % 8 == 0`) separates the two.

---

## 7. EXEPACK ≠ a compressed image

Packed EXEs (`BRIEFING`, `CHOICE`, `OPENING`, `REPORT`, `STARTUP`, `MAKEINIT`)
have `nreloc = 0`, an entry point near EOF and the string `Packed file is
corrupt`. It is easy to conclude that the image is compressed and offsets are
invalid.

In fact only the **relocation table** is compressed there. The stub at image
`0x25192` (relocation decoder `0x251FC`, opcodes `0xB0` = fill, `0xB2` = copy)
expands just that table; the program code sits untouched in the image. Strings
can therefore be read with the usual formula
`image offset = file offset − hdrsize*16`.

---

## 8. The save-state `Vga` blob: plane stride is `0x10000`, not `0x8000`

The physical GVRAM stride on PC-98 is `0x8000`. In the `Vga` blob from a `.sav`
it is different: `base = 0x07C000`, plane stride `0x10000`. With the wrong
stride the render comes out as noise — and that is why the screen contents went
unseen for a long time.

```powershell
python tools\render_vram.py dump\Vga.bin out\screen.png
```

---

## 9. A screenshot taken with Windows tooling cannot yield the palette reliably

Two separate pains:

* **scaling.** A window capture comes out at, say, 937×458 — neither 640×400 nor
  a uniform scale. Pixel-level alignment with GVRAM does not work.
* **no `.pal` sidecar.** Only DOSBox-X itself writes the palette, on **Ctrl+F5**
  (`<name>.pal` appears next to `<name>.png`).

Additionally, if the image went through JPEG, values in flat areas drift by ±3
— so searching for the palette by exact colour match either produces false
positives or nothing at all.

---

## 10. Small but important

* **`--palette` in an early version of the extractor was broken**: the `E`
  intensity bit was lost, so indices 8..15 came out black. If your PNGs look
  "dark", check the palette.
* **Zero-length entries** occur (in `CHARA.PCK` they are `#26`…`#36`) — they must
  be skipped, otherwise the header test reads garbage.
* **`S_ROLL.ASK`** was long considered corrupt: it did not decode with the
  12-byte-header variant. In fact it is a "raw block" (`u32` + stream from
  offset 4) and a perfectly valid 640×320 frame.
* **`pal98 grb`** is the signature of the MAG text palette format, not a
  reference to a palette file. There is no text `.pal` anywhere in the game
  data; the string only exists in the EXEs as a library constant.
