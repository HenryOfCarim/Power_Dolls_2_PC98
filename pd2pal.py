"""Power Dolls 2 (PC-98) palette tools.

How the game sets the palette
-----------------------------
`BRIEFING.EXE` image `0x10A59` (identical code exists in every graphics EXE):

    for (i = 0; i < 16; i++) {
        b0 = es:[bx + 0x0C];            /* bx = struct + i*2                  */
        b1 = es:[bx + 0x0B];
        out(0xA8, b0 >> 4);             /* palette index                      */
        out(0xAA, b0 & 15);             /* R                                  */
        out(0xAC, b1 >> 4);             /* G                                  */
        out(0xAE, b1 & 15);             /* B                                  */
    }

So a palette is 32 bytes:
    byte[2i] = (index << 4) | R
    byte[2i+1] =  G << 4    | B

Where that 32-byte table lives
------------------------------
* every `.GCP` file, at offset **0xB** (26/26 validate).
  Most carry the standard PC-98 default palette; `HARDY.GCP` and `KOGADO.GCP`
  carry custom artwork palettes.
* 27 entries of `CHARA.PCK`, likewise at offset 0xB.

What is NOT a palette source
----------------------------
* `.ASK` / `.PCK` image entries - the container is only
  `u32 decoded_size; u16 x; u16 y; u16 w; u16 h` + LZSS stream from offset 12.
  (The 48 bytes at offset 12 are the start of the compressed stream, not a
  palette.)
* `.SLD` files and the `u32 decoded_size + LZSS @ 4` block form: data only.
* DOSBox-X save states: the PC-98 palette is hardware state and is not
  serialised (`Vga`, `Render`, `Pic`, `Mixer`, `CPU` all searched).

Usage
-----
    python pd2pal.py --list  hdi/PD2D                 # every palette in the game data
    python pd2pal.py --gcp   hdi/PD2D/HARDY.GCP -o hardy.pal
    python pd2pal.py --pck   hdi/PD2D/CHARA.PCK --entry 3
    python pd2pal.py --read  capture/game.pal         # a DOSBox-X .pal sidecar
    python pd2pal.py --shot  capture/game.png --vram dump/Vga.bin -o derived.pal
    python pd2pal.py --default -o pc98default.pal
"""
import os, sys, struct, argparse, collections

DEFAULT_PALETTE = [(0,0,0),(0,0,15),(0,15,0),(0,15,15),(15,0,0),(15,0,15),(15,15,0),(15,15,15),
                   (7,7,7),(0,0,10),(0,10,0),(0,10,10),(10,0,0),(10,0,10),(10,10,0),(10,10,10)]
"""The palette stored in 24 of the 26 .GCP files (offset 0xB)."""


# ---------------------------------------------------------------- packed table
def palette_from_packed(blob, base=0):
    """32-byte packed palette at base+0x0B. Returns list of 16 (R,G,B) or None."""
    if base + 0x0B + 32 > len(blob):
        return None
    out = []
    for i in range(16):
        b0 = blob[base + 0x0C + 2*i]
        b1 = blob[base + 0x0B + 2*i]
        if (b0 >> 4) != i:
            return None
        out.append((b0 & 15, b1 >> 4, b1 & 15))
    return out


def palette_to_packed(pal):
    out = bytearray()
    for i, (r, g, b) in enumerate(pal):
        out.append(((i & 15) << 4) | (r & 15))
        out.append(((g & 15) << 4) | (b & 15))
    return bytes(out)


# ------------------------------------------------------------------ .pal files
def read_pal(path):
    """-> list of 16 (R,G,B) with 4-bit components (0..15)."""
    d = open(path, 'rb').read()
    if d[:8] == b'JASC-PAL':
        lines = d.decode('latin1').splitlines()
        n = int(lines[2])
        pal = []
        for ln in lines[3:3 + n]:
            r, g, b = (int(x) for x in ln.split()[:3])
            pal.append((r >> 4, g >> 4, b >> 4))
        return pal
    if len(d) >= 768:
        pal = []
        for i in range(16):
            r, g, b = d[i*3], d[i*3+1], d[i*3+2]
            pal.append((r >> 4, g >> 4, b >> 4))
        return pal
    if len(d) == 48:
        return [tuple(d[i*3:i*3+3]) for i in range(16)]
    # plain text "R G B" lines, either 0..15 or 0..255
    try:
        pal = []
        for ln in d.decode('latin1').splitlines():
            p = ln.split()
            if len(p) >= 3 and all(x.isdigit() for x in p[:3]):
                pal.append(tuple(int(x) for x in p[:3]))
        if len(pal) >= 16:
            pal = pal[:16]
            if max(max(c) for c in pal) > 15:
                pal = [(r >> 4, g >> 4, b >> 4) for r, g, b in pal]
            return pal
    except Exception:
        pass
    raise ValueError(f"unrecognised palette file: {path}")


def write_pal(path, pal, fmt='jasc'):
    if fmt == 'jasc':
        with open(path, 'w', newline='\n') as f:
            f.write("JASC-PAL\n0100\n16\n")
            for r, g, b in pal:
                f.write(f"{r*17} {g*17} {b*17}\n")
    elif fmt == 'raw':
        with open(path, 'wb') as f:
            for r, g, b in pal:
                f.write(bytes([r*17, g*17, b*17]))
    else:   # nibbles, the game's own 48-byte form
        with open(path, 'wb') as f:
            for r, g, b in pal:
                f.write(bytes([r, g, b]))


def show(pal):
    return " ".join(f"{r:x}{g:x}{b:x}" for r, g, b in pal)


# --------------------------------------------------------------- screenshot way
def derive_from_shot(shot, vram, sx, sy, ox, oy, base=0x07C000, gap=0x10000):
    """Read the palette out of a rendered screenshot using the emulator's GVRAM.

    `shot` must be an unscaled 640x400 grab (DOSBox-X Ctrl+F5) so that the
    index image and the screenshot line up 1:1.
    """
    import numpy as np
    from PIL import Image
    W, H, NB = 640, 400, 80
    v = open(vram, 'rb').read()
    I = np.zeros((H, W), dtype=np.uint8)
    for k in range(4):
        p = np.frombuffer(v[base+k*gap: base+k*gap+H*NB], dtype=np.uint8).reshape(H, NB)
        I |= np.unpackbits(p, axis=1, bitorder='big').reshape(H, NB*8).astype(np.uint8) << k
    S = np.asarray(Image.open(shot).convert('RGB'))
    ys = np.rint(oy + np.arange(H) * sy).astype(int)
    xs = np.rint(ox + np.arange(W) * sx).astype(int)
    ok_y = (ys >= 0) & (ys < S.shape[0]); ys = ys[ok_y]
    ok_x = (xs >= 0) & (xs < S.shape[1]); xs = xs[ok_x]
    sub = I[np.ix_(np.arange(H)[ok_y], np.arange(W)[ok_x])]
    col = S[np.ix_(ys, xs)]
    codes = (col[:, :, 0].astype(np.int32) << 16) | (col[:, :, 1].astype(np.int32) << 8) | col[:, :, 2].astype(np.int32)
    fi = sub.ravel(); fc = codes.ravel()
    pal = [None]*16
    good = tot = 0
    for v_ in range(16):
        m = fi == v_
        if m.sum() < 20:
            continue
        cnt = collections.Counter(fc[m])
        (code, n) = cnt.most_common(1)[0]
        r = ((code >> 16) & 255) >> 4
        g = ((code >> 8) & 255) >> 4
        b = (code & 255) >> 4
        pal[v_] = (r, g, b)
        good += n; tot += int(m.sum())
    return pal, good / max(1, tot)


def main():
    ap = argparse.ArgumentParser(description="Power Dolls 2 palette tools")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--list', metavar='DIR')
    g.add_argument('--gcp', metavar='FILE')
    g.add_argument('--pck', metavar='FILE')
    g.add_argument('--read', metavar='FILE.pal')
    g.add_argument('--shot', metavar='FILE.png')
    g.add_argument('--default', action='store_true')
    ap.add_argument('--entry', type=int, default=None)
    ap.add_argument('--vram', metavar='Vga.bin')
    ap.add_argument('--sx', type=float, default=1.0)
    ap.add_argument('--sy', type=float, default=1.0)
    ap.add_argument('--ox', type=int, default=0)
    ap.add_argument('--oy', type=int, default=0)
    ap.add_argument('-o', '--out')
    ap.add_argument('--fmt', default='jasc', choices=['jasc', 'raw', 'nibbles'])
    a = ap.parse_args()

    pal = None
    if a.default:
        pal = DEFAULT_PALETTE
    elif a.read:
        pal = read_pal(a.read)
    elif a.gcp:
        d = open(a.gcp, 'rb').read()
        pal = palette_from_packed(d)
        if pal is None:
            sys.exit(f"{a.gcp}: no packed palette at offset 0xB")
    elif a.pck:
        d = open(a.pck, 'rb').read()
        tbe = struct.unpack_from('<I', d, 0)[0]
        if tbe == 0 or tbe % 8 or tbe+4 > len(d):
            sys.exit(f"{a.pck}: not a PD2 archive")
        n = tbe // 8
        if a.entry is None:
            for i in range(n):
                off, sz = struct.unpack_from('<II', d, 4+i*8)
                e = d[tbe+4+off: tbe+4+off+sz]
                p = palette_from_packed(e)
                if p:
                    print(f"#{i:<3d} {show(p)}")
            sys.exit(0)
        off, sz = struct.unpack_from('<II', d, 4+a.entry*8)
        e = d[tbe+4+off: tbe+4+off+sz]
        pal = palette_from_packed(e)
        if pal is None:
            sys.exit(f"{a.pck}#{a.entry}: no packed palette at offset 0xB")
    elif a.shot:
        if not a.vram:
            sys.exit("--shot needs --vram <Vga.bin> from a save state of the same screen")
        pal, conf = derive_from_shot(a.shot, a.vram, a.sx, a.sy, a.ox, a.oy)
        print(f"# index -> colour, alignment confidence {conf:.3f}")
        for i, c in enumerate(pal):
            print(f"  [{i:2d}] {'--' if c is None else '%x%x%x' % c}")
        if conf < 0.9:
            print("# WARNING: low confidence - the screenshot and the save state are probably\n"
                  "#          not the same screen, or the scale/offset are wrong.")
        if pal is None or any(c is None for c in pal):
            sys.exit("incomplete palette")

    print(show(pal))
    if a.out:
        write_pal(a.out, pal, a.fmt)
        print(f"wrote {a.out} ({a.fmt})")


if __name__ == '__main__':
    main()
