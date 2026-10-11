> 🌐 **English** · [Українська](FORMAT.uk.md)

# Power Dolls 2 (PC-98) graphics format — full breakdown

This document is self-contained: it can be read cold, with no prior context.
Everything below is either **verified against bytes** or explicitly marked as
unverified.

The source of truth is the disassembler. Addresses are given in EXE **image**
space (file offset = image offset + `hdrsize*16`) for the HDI build of
`CONVERT.EXE`.

---

## 1. Terminology

| term | meaning |
|---|---|
| **image** | the contents of an EXE after the MZ header: `file[hdrsize*16 : hdrsize*16 + (pages-1)*512 + lastpage - hdrsize*16]` |
| **stream** | the compressed data the codec reads |
| **entry** | one block inside a `.PCK` archive |
| **GVRAM** | PC-98 video memory: `B=0xA8000`, `R=0xB0000`, `G=0xB8000`, `E=0xE0000`, row stride 80 bytes |

---

## 2. Containers

There are exactly **three** container formats, and all of them use the **same
codec**.

### 2.1 `.ASK` — a single picture

```
offset  0  u32 decoded_size        # == width * height / 2
offset  4  u16 x                   # screen X coordinate, in pixels
offset  6  u16 y                   # screen Y coordinate
offset  8  u16 width               # multiple of 8
offset 10  u16 height
offset 12  ... LZSS stream ...
```

The loader (`CONVERT.EXE` image `0x539C`, called as `lcall 0x539, 0xc`) opens
the file, **reads and discards the first 4 bytes**
(`fread(&tmp, 4, 1, fp)`), after which the caller reads four 2-byte values —
12 bytes in total. The codec then reads from the same `FILE*`. So **the stream
starts at offset 12**.

`.ASK` is not a script. Twelve of the thirteen `.ASK` files in the game carry
this header and are pictures:

| file | size | what it is |
|---|---|---|
| `GAMEOVER.ASK` | 640×400 | the "GAME OVER" screen |
| `SELMA.ASK`, `MAND.ASK`, `M_FAIL.ASK`, `SINGLE.ASK` | 640×400 | full-screen pictures |
| `OP_AS0.ASK` | 352×395 | a frame |
| `ST07`…`ST12.ASK` | 192×66 | tiles (y = 0, 66, 132, 198, 330) |
| `GOONPD2.ASK` | 272×14 (x=184, y=186) | a banner |
| `S_ROLL.ASK` | — | **the exception:** a "raw block", see §2.3 |

### 2.2 `.PCK` — an archive

```
u32 offset_table_end                     # table length (multiple of 8)
(offset_table_end / 8) x { u32 data_offset; u32 file_size }
data begins at offset_table_end + 4
entry i = file[offset_table_end + 4 + data_offset : + file_size]
```

Verified across all 39 archives: `data_offset` is cumulative from zero and the
final entry ends exactly at EOF.

Entries come in **two kinds**, distinguished by the test

```python
decoded_size == width * height / 2      # and width % 8 == 0
```

| kind | examples | what it is |
|---|---|---|
| **pictures** | `FACE`, `DFACE`, `ARMS`, `EVKAO`, `WEAPON`, `HIDAN`, `DATAU`, `EVENT`, `M_CLR`, `SMAP`, `MMAP`, `SCORE_N` (27/38), `SCORE_P`, `STAFF_G`, `STAFF_P`, `BLANC`, `OP_AS` (1/29) | the same format as `.ASK` |
| **display lists** | `CHARA`, `ANIME`, `MES`, `WMES`, `INIT`, `NAMES`, `MOJI`, `NPC`, `MAP_CHG`, `MISSON*D`, `MUNIT`, `TUNIT`, `SCEN_MIS`, `YAOUPD1` | GDC commands (the same style as `.GCP`) |

Entries of the second kind **are not rasters** — trying to "decode them as a
picture" is pointless.

### 2.3 "Raw block": `u32` + LZSS from offset 4

```
offset 0  u32 decoded_size
offset 4  ... LZSS stream ...
```

Every `.SLD` is built this way (`HUNIT`, `KIRI`, `MES0`, `RMES`, `OP_EYES`,
`OP_WAI_A/B/C`), and so is **`S_ROLL.ASK`** (640×320, `decoded_size = 102400`).

How to tell it apart from §2.1: with the correct variant the stream is consumed
**right down to the last byte** (`used == file_size - start`, discrepancy ≤ 1
byte — the tail of the bit buffer). For `S_ROLL.ASK` the 12-byte-header variant
yields 102262 bytes and then hits the end of the stream — i.e. it is wrong.

### 2.4 `.GCP` — NOT a picture

`.GCP` is a **command list for the PC-98 GDC hardware**. The handler at
`CONVERT.EXE` image `0x5CE2`:

* opens the file and reads it whole into a buffer;
* `mov dx,0x7c / out dx,al` and `mov dx,0x7e / out dx,al` — it writes directly
  to the GDC ports;
* takes bytes at offsets `0,1,2,3` and (conditionally) `8,9,10`;
* computes the destination address as `y*0x50 + x/8` (VRAM stride = 80).

A `.GCP` header is 12 bytes, followed by a **32-byte palette at offset `0xB`**
(see [`PALETTE.md`](PALETTE.md)) and then commands from offset `0x2B`.

The same applies to the "display list" entries inside `.PCK` files — they have
an identical header structure (`struct[8] == 0x22`).

---

## 3. The codec

Recovered from `CONVERT.EXE`, image **`0x54E6`**, entry point
`lcall 0x539, 0x156`. C signature: `decode(far *handle, byte *out, int len)`.

### 3.1 State structure

```
+0x0000  u16 match_base    absolute ring index to copy from
+0x0002  u16 match_len     copy length
+0x0004  u16 wpos          ring write index, masked & 0xFFF
+0x0006  u16 state         0/1 = token boundary, 2 = resuming a copy
+0x0008  u16 match_i       resume index inside a copy
+0x000A  u16 bitbuf        bit buffer
+0x000C  u8  ring[4096]    ring buffer
+0x101D  FILE *fp
```

Initialisation (`0x539C` / `0x5459`, `enter 8,0`, `malloc(0x101F)`):

```
ring[0 .. 0xFED] = 0        // 4078 bytes
wpos   = 0xFEE              // 4078
bitbuf = 0
state  = 0
the first 4 bytes of the file are read and discarded
```

Note: the ring is 4096 bytes (mask `0xFFF`), but only the first 4078 are zeroed
and the write pointer starts at 4078. This is not a misreading — that is
literally what the code does (`cmp word ptr es:[bx], 0xFEE` /
`mov word ptr es:[bx+4], 0xFEE`).

### 3.2 Bit reader

```c
bitbuf >>= 1;
if ((bitbuf & 0x100) == 0)
        bitbuf = 0xFF00 | fgetc(fp);      /* 8 bits per byte, LSB-first */
bit = bitbuf & 1;
```

The `0x100` sentinel means "there are still unused bits in the buffer". After
`bitbuf = 0xFF00 | c` bit 8 is set, and it clears after exactly 8 shifts.
The bit order is therefore **least significant first**.

### 3.3 Tokens

```c
if (bit == 1) {                     /* literal */
        b = fgetc(fp);
        ring[wpos] = b;
        wpos = (wpos + 1) & 0xFFF;
        *out++ = b;
} else {                            /* copy: two bytes c1, c2 */
        c1 = fgetc(fp);
        c2 = fgetc(fp);
        base  = c1 | ((c2 & 0xF0) << 4);   /* 12-bit ABSOLUTE index */
        count = (c2 & 0x0F) + 3;           /* see pitfall 2 below */
        for (i = 0; i < count; i++) {
                b = ring[(base + i) & 0xFFF];
                ring[wpos] = b;
                wpos = (wpos + 1) & 0xFFF;
                *out++ = b;
        }
}
```

### 3.4 The two pitfalls that break a "normal" LZSS

**Pitfall 1 — the offset is absolute, not relative.**
`base` is an **index into the ring**, not a distance back from `wpos`. Canonical
LZSS reads `ring[(wpos - offset) & mask]`; here it is
`ring[(base + i) & 0xFFF]`. The encoder therefore stores the absolute position
of the match.

**Pitfall 2 — the length is one greater than `add ax,2` suggests.**
The assembly says `add ax, 2`, but the copy loop is tested as

```
0x56EF  mov ax, es:[bx+2]      ; match_len
0x56F2  cmp ax, word ptr [bp-4]; cmp len, i
0x56F5  jge 0x569B             ; if len >= i -> copy
```

so the body runs for `i = 0 … len` **inclusive** — one extra iteration.
The real length is `(c2 & 0x0F) + 3`.

Evidence: a parameter sweep in which the length is `+3` reproduces exactly
`decoded_size` on all four test entries, while `+2` does not.

### 3.5 Output: 4 bits per pixel, interleaved

The output is **not** "four consecutive planes" but **4 bytes per group of
8 pixels**:

```
for each row y = 0 .. height-1:
  for each byte column xb = 0 .. width/8 - 1:
     byte 0 -> plane B  (colour bit 0)
     byte 1 -> plane R  (colour bit 1)
     byte 2 -> plane G  (colour bit 2)
     byte 3 -> plane E  (colour bit 3)
```

Total size `width/8 * height * 4 == width*height/2` ✔

**The order is proven by the GVRAM blit code** (`CONVERT.EXE` image `0x5B1F`):

```
0x5B23  mov ax,0xA800        ; B plane
0x5B2B  mov si,0x8AEC        ; staging buffer holding stream byte 0
        rep movsw / movsb    ; -> 0xA8000 + offset

0x5B42  add di,0x8000        ; R plane (0xB0000)
0x5B46  mov si,0x8A9C        ; byte 1

0x5B53  mov ax,0xB800        ; G plane
0x5B5A  mov si,0x8A4C        ; byte 2

0x5B67  mov ax,0xE000        ; E plane
0x5B6E  mov si,0x89FC        ; byte 3

0x5B81  add word ptr [bp-0x38], 0x50   ; VRAM row stride = 80
```

So the byte order in the stream is `B, R, G, E`, i.e. colour bits `0,1,2,3`.

**Bits within a byte are most-significant first** (leftmost pixel = bit 7).
Bit reversal (a 256-byte table built at image `0x57AD` with `shr/rcl`) is
**not** applied in the normal path: it is only needed when the 5th argument of
`DrawPicture` is non-zero (test at image `0x592C`). In that same mode the plane
rows are also byte-swapped by the helper at `0x5C2C` (`mov al,[si] / mov
al,[di] / mov [si],…` — swapping two bytes).

### 3.6 Why there is no intermediate buffer in memory

`DrawPicture` (image `0x5723`) calls the codec **4 bytes at a time** and
immediately scatters them into four plane staging buffers (80 bytes each, DGROUP
`0x89FC/0x8A4C/0x8A9C/0x8AEC`). No 4608-byte intermediate buffer ever exists —
which is exactly why earlier searches for "the decoder's output in RAM" found
nothing.

---

## 4. Proof of correctness

The codec is considered correct on these grounds:

1. **Visually.** `GAMEOVER.ASK` yields a perfectly legible "GAME OVER" screen
   over the repeated "POWER DoLLS 2" pattern. `M_CLR.PCK` yields full
   "MISSION COMPLETE / Congratulations!" screens with portraits and legible
   names (Alice Knox, Selma Shaldon, …). `WEAPON`/`ARMS`/`FACE`/`DFACE`/`EVKAO`
   produce clean images. A random byte stream cannot do that.
2. **Statistics.** The output is 20–78 % zero bytes with uniform runs up to
   **2176 bytes**. For random data: 0.3 % and a maximum of 2.
3. **Stream consumption.** The codec consumes the whole stream (exactly 1 byte
   remains — the bit-buffer tail) on **all 360** images.
4. **Code identity.** The decoder in `TACTICS.EXE` and `BRIEFING.EXE` is
   byte-for-byte identical to `CONVERT.EXE` except for 12–16 bytes — and all of
   those sit inside `lcall` immediates pointing at the runtime (`fgetc`,
   `exit`). It is a single statically linked library routine.

### What is **not** a criterion

"the decoder emitted exactly `decoded_size` bytes" is **not proof**. LZSS pads
itself: it can produce any requested length from an empty ring. Measured:
**360/360 entries "pass" that test for 40 different parameter sets**, including
wrong ones. The only reliable criteria are visual legibility and an exact match
against GVRAM.

---

## 5. What lives where — archive summary

| archive | entries | pictures | cell sizes |
|---|---:|---:|---|
| `FACE.PCK` | 38 | 38 | 96×96 |
| `DFACE.PCK` | 38 | 38 | 80×96 |
| `ARMS.PCK` | 69 | 69 | 192×46, 80×128, 216×32, 32×144 |
| `EVKAO.PCK` | 23 | 23 | 128×128 |
| `WEAPON.PCK` | 13 | 13 | 208×316, 384×112, 432×144 |
| `HIDAN.PCK` | 7 | 7 | 112×168 |
| `DATAU.PCK` | 30 | 30 | 112×164, 192×68 |
| `EVENT.PCK` | 19 | 19 | 128×256, 256×128 |
| `M_CLR.PCK` | 11 | 11 | 640×400 |
| `STAFF_G.PCK` | 5 | 5 | 640×400 |
| `STAFF_P.PCK` | 7 | 7 | 96×32 … 304×72 |
| `SMAP.PCK` | 12 | 12 | 360×360 |
| `MMAP.PCK` | 12 | 12 | 144×144 |
| `SCORE_N.PCK` | 38 | 27 | 112×20 … 264×22 |
| `SCORE_P.PCK` | 29 | 29 | 24×24 … 56×22 |
| `BLANC.PCK` | 7 | 7 | as ARMS |
| `OP_AS.PCK` | 29 | 1 | 352×395 |
| `CHARA.PCK` | 38 | 0 | display lists (+ a palette in each entry) |
| the rest | 3–17 | 0 | text / display lists |

### Exceptions and details

* `SCORE_N.PCK` — 27 of 38 entries are pictures; the other 11 are a different
  kind of data.
* `OP_AS.PCK` — only 1 entry passes the header test.
* Entries with `file_size == 0` (in `CHARA.PCK` these are `#26`…`#36`) must be
  skipped.
* `FACE.PCK` differs between the **floppy** and **HDI** releases: 36 entries
  versus 38, and entry 0 differs too. Never mix the two releases.

---

## 6. What remains unknown

* **The compressor.** The packer is in `CONVERT.EXE` (it owns both the
  `.pck`/`.gcp` extensions and the strings `rb`/`wb`,
  `File is not found <%s>`). Look next to the decoder at image `0x54E6`.
* **`.GCP` / display lists.** The command semantics were not worked out
  (handler `0x5CE2`). Only needed if these screens must be reproduced without
  the game.
* **Exact palettes of the artwork screens** — solved: the tables ship inside the
  EXEs (48 bytes, channel order B,R,G) — [`PALETTE_TABLES.md`](PALETTE_TABLES.md),
  `tools/pal_tables.py`, or `pd2extract.py --pal-exe "FILE.EXE:0xOFFSET"`.
