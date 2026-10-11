"""Power Dolls 2 (PC-98, Kogado 1994) graphics: decoder + extractor.

Recovered by static analysis of CONVERT.EXE (Borland C++ 1991, large model,
DGROUP image offset 0x9210):

  extension dispatcher   image 0x5723  (DrawPicture / LoadPicture)
    .ASK  -> open the file, LZSS decode        -> image 0x539C (open), 0x54E6 (decode)
    .GCP  -> image 0x5CE2                      (different codec, see notes)
    .PCK  -> image 0x5D6E  (entry via 0x5C4A)

The LZSS decoder at image 0x54E6 (`lcall 0x539,0x156`):

  struct handle {
      u16 match_base;      // +0x00  absolute ring index of the match source
      u16 match_len;       // +0x02  (c2 & 0x0F) + 3
      u16 wpos;            // +0x04  ring write index, & 0xFFF
      u16 state;           // +0x06  0/1 = token boundary, 2 = resuming a match
      u16 match_i;         // +0x08  resume index
      u16 bitbuf;          // +0x0A
      u8  ring[4096];      // +0x0C
      FILE *fp;            // +0x101D
  }

  On open: ring[0 .. 0xFED] = 0, wpos = 0xFEE, bitbuf = 0, state = 0.
  On open the first 4 bytes of the file are read and discarded (decoded_size),
  then the caller reads x, y, width, height as 4 u16 -> the stream starts at 12.

  Bit reader is LSB-first, one byte feeds 8 bits:
      bitbuf >>= 1
      if (bitbuf & 0x100) == 0: bitbuf = 0xFF00 | getc()
      bit = bitbuf & 1
  Token:
      bit == 1 -> literal: next byte
      bit == 0 -> two bytes c1,c2:
                    ring_index = c1 | ((c2 & 0xF0) << 4)     (12 bit, ABSOLUTE)
                    count      = (c2 & 0x0F) + 3
                  (the +3 is real: the copy loop tests `cmp len,i / jge`, so it
                   runs for i = 0 .. len inclusive -- one more than the +2 that
                   the `add ax,2` suggests)
      Every byte produced is also appended to the ring.

  Output is 4 bits per pixel, stored *interleaved*: per 8-pixel column group,
  4 bytes, one per bit plane, in the order the game blits to the PC-98 GVRAM
  planes.  Total = width/8 * height * 4 == width*height/2.

  The game writes plane byte 0 -> the staging area's highest address and byte 3
  -> the lowest, i.e. the stream order is the reverse of the B,R,G,E VRAM order:
      stream byte 0 = E plane (colour bit 3)
      stream byte 1 = G plane (colour bit 2)
      stream byte 2 = R plane (colour bit 1)
      stream byte 3 = B plane (colour bit 0)
  A 256-entry bit-reversal table built at image 0x57AD is used before storing.

There is NO inline palette.  The 48 bytes at entry offset 12 that earlier work
mistook for a 16-colour RGB palette are simply the first 48 bytes of the
compressed stream -- which is why they repeat across images of the same family
and are constant across all 26 .GCP-like headers.
"""
import os, struct

__all__ = ["decode_lzss", "parse_entry", "parse_archive", "parse_ask",
           "planes_from_stream", "indices_from_planes", "is_image_entry",
           "is_raw_block", "raw_geometry", "PC98_DEFAULT_PALETTE"]

RING = 4096
WPOS0 = 0xFEE
HEADER = 12

REV8 = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


class Truncated(Exception):
    pass


def decode_lzss(data, start, outlen, *, ring=RING, wpos0=WPOS0):
    """Faithful reimplementation of the game's decoder (image offset 0x54E6)."""
    r = bytearray(ring)
    wpos = wpos0
    pos = start
    bitbuf = 0
    n = len(data)
    out = bytearray()

    def getbyte():
        nonlocal pos
        if pos >= n:
            raise Truncated(f"input exhausted at {len(out)}/{outlen}")
        v = data[pos]
        pos += 1
        return v

    while len(out) < outlen:
        bitbuf >>= 1
        if not (bitbuf & 0x100):
            bitbuf = 0xFF00 | getbyte()
        if bitbuf & 1:
            c = getbyte()
            r[wpos] = c
            wpos = (wpos + 1) & 0xFFF
            out.append(c)
        else:
            c1 = getbyte()
            c2 = getbyte()
            off = c1 | ((c2 & 0xF0) << 4)
            ln = (c2 & 0x0F) + 3
            for i in range(ln):
                b = r[(off + i) & 0xFFF]
                r[wpos] = b
                wpos = (wpos + 1) & 0xFFF
                out.append(b)
                if len(out) == outlen:
                    break
    return bytes(out), pos


def is_image_entry(blob):
    if len(blob) < HEADER:
        return False
    sz, x, y, w, h = struct.unpack_from('<IHHHH', blob, 0)
    return bool(w) and bool(h) and w % 8 == 0 and sz == w * h // 2


def parse_entry(blob, start=HEADER):
    """Decode one image block -> dict."""
    sz, x, y, w, h = struct.unpack_from('<IHHHH', blob, 0)
    out, used = decode_lzss(blob, start, sz)
    return dict(size=sz, x=x, y=y, w=w, h=h,
                stream=len(blob) - start, used=used - start,
                stream_bytes=out)


def parse_archive(path):
    """-> list of (index, blob) for a .PCK archive."""
    d = open(path, 'rb').read()
    tbe = struct.unpack_from('<I', d, 0)[0]
    if tbe == 0 or tbe % 8 or tbe + 4 > len(d):
        raise ValueError("not a PD2 archive")
    out = []
    for i in range(tbe // 8):
        off, sz = struct.unpack_from('<II', d, 4 + i * 8)
        out.append((i, d[tbe + 4 + off: tbe + 4 + off + sz]))
    return out


def parse_ask(path):
    """A standalone .ASK / .GCP-style single image file."""
    return parse_entry(open(path, 'rb').read())


# ------------------------------------------------------------- "raw block" form
# A third container form, used by every .SLD and by S_ROLL.ASK:
#     offset 0  u32 decoded_size
#     offset 4  ... LZSS stream ...
# The decoded bytes are the same interleaved 4-plane data a normal entry gives,
# but the block carries no width/height, so the geometry has to be supplied or
# derived from decoded_size (w*h/2 == decoded_size).
RAW_MIN = 16
RAW_MAX = 8_000_000
RAW_SIZES = ((640, 320), (640, 400), (640, 200), (320, 200), (640, 480))


def is_raw_block(blob):
    """Decoded bytes if blob is `u32 decoded_size` + LZSS from offset 4, else None."""
    if len(blob) < RAW_MIN:
        return None
    n = struct.unpack_from('<I', blob, 0)[0]
    if not (RAW_MIN <= n <= RAW_MAX):
        return None
    try:
        out, used = decode_lzss(blob, 4, n)
    except Exception:
        return None
    # the decisive test: the stream must be consumed to the last byte
    if len(out) == n and used >= len(blob) - 1:
        return out
    return None


def raw_geometry(decoded_size, sizes=RAW_SIZES):
    """(w, h) with w*h/2 == decoded_size, or None if no known screen size fits."""
    for w, h in sizes:
        if w * h // 2 == decoded_size:
            return w, h
    return None


def planes_from_stream(stream, w, h, stream_order=(0, 1, 2, 3)):
    """stream_order[k] = colour bit of stream byte k.

    PROVEN from the blit code at CONVERT.EXE image 0x5B1F: stream byte 0 goes to
    the staging buffer at DGROUP:0x8AEC which is copied to segment 0xA800 (B),
    byte 1 -> 0x8A9C -> 0xB000 (R), byte 2 -> 0x8A4C -> 0xB800 (G),
    byte 3 -> 0x89FC -> 0xE000 (E).  So the order is B, R, G, E = bits 0,1,2,3.
    """
    nb = w // 8
    planes = [bytearray() for _ in range(4)]
    o = 0
    for _y in range(h):
        for _xb in range(nb):
            for k in range(4):
                planes[stream_order[k]].append(stream[o])
                o += 1
    return [bytes(p) for p in planes]


def indices_from_planes(planes, w, h, reverse_bits=False):
    """-> bytes, one palette index per pixel, row major.

    reverse_bits=False for the normal draw path.  The bit-reversal table built at
    CONVERT.EXE image 0x57AD is only used when DrawPicture's 5th argument is
    non-zero (image 0x592C tests it); that path also byte-swaps plane rows via
    the helper at 0x5C2C.
    """
    nb = w // 8
    out = bytearray(w * h)
    o = 0
    for y in range(h):
        base = y * w
        for xb in range(nb):
            vals = []
            for k in range(4):
                v = planes[k][o]
                vals.append(REV8[v] if reverse_bits else v)
            o += 1
            for bit in range(8):
                idx = 0
                for k in range(4):
                    idx |= ((vals[k] >> (7 - bit)) & 1) << k
                out[base + xb * 8 + bit] = idx
    return bytes(out)


# PC-98 16-colour digital palette, GRB, 4 bits per channel.
# This is the standard hardware reset palette; the game overwrites it at runtime.
PC98_DEFAULT_PALETTE = [
    (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
    (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
    (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
    (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
]

if __name__ == '__main__':
    import sys
    p = sys.argv[1]
    if p.lower().endswith('.pck'):
        for i, blob in parse_archive(p):
            if is_image_entry(blob):
                r = parse_entry(blob)
                print(f"#{i:3d} {r['w']}x{r['h']} at ({r['x']},{r['y']}) "
                      f"decoded={len(r['stream_bytes'])}/{r['size']} used={r['used']}/{r['stream']}")
    else:
        r = parse_ask(p)
        print(f"{p}: {r['w']}x{r['h']} at ({r['x']},{r['y']}) "
              f"decoded={len(r['stream_bytes'])}/{r['size']} used={r['used']}/{r['stream']}")
