"""Find the blob-plane -> colour-bit order that makes a VRAM render self-consistent.

The proof of a correct render is simple: in an indexed-colour screen every pixel
index maps to exactly ONE rendered colour. If the plane order is wrong, one
index collects many colours. So: brute-force the 24 orders, and for each count
how many of the 16 indices map to more than one colour in the emulator PNG.

The order that yields 0 collisions (and ~1.0 confidence) is the real one, and
the colour it assigns to each index IS the on-screen palette.

Usage:
    python tools\\plane_order.py <Vga.bin> <screenshot.png> [--min-px 30]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import sys
from pathlib import Path

BASE, GAP, W, H, NB = 0x07C000, 0x10000, 640, 400, 80


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vram")
    ap.add_argument("shot")
    ap.add_argument("--min-px", type=int, default=30)
    a = ap.parse_args()

    import numpy as np
    from PIL import Image

    v = Path(a.vram).read_bytes()
    if len(v) < BASE + 4 * GAP:
        sys.exit(f"{a.vram}: too short ({len(v)} bytes)")
    planes = []
    for k in range(4):
        p = np.frombuffer(v[BASE + k * GAP: BASE + k * GAP + H * NB],
                          dtype=np.uint8).reshape(H, NB)
        planes.append(np.unpackbits(p, axis=1, bitorder="big")
                      .reshape(H, NB * 8).astype(np.uint8)[:, :W])

    img = np.asarray(Image.open(a.shot).convert("RGB"))
    if img.shape[0] != H or img.shape[1] != W:
        sys.exit(f"{a.shot}: expected {W}x{H}, got {img.shape[1]}x{img.shape[0]} "
                 "(pass an unscaled Ctrl+F5 grab)")
    codes = (img[:, :, 0].astype(np.int32) << 16) | (img[:, :, 1].astype(np.int32) << 8) | img[:, :, 2].astype(np.int32)
    codes = codes.ravel()

    print(f"{a.vram} + {a.shot}\n")
    print("order   collisions  confidence  palette")
    best = []
    for perm in itertools.permutations(range(4)):
        I = np.zeros((H, W), dtype=np.uint8)
        for bit, k in enumerate(perm):
            I |= planes[k] << bit
        fi = I.ravel()
        pal, good, tot, coll = [None] * 16, 0, 0, 0
        for val in range(16):
            m = fi == val
            n = int(m.sum())
            if n < a.min_px:
                continue
            cnt = collections.Counter(codes[m].tolist())
            (code, hit), = cnt.most_common(1)
            pal[val] = (((code >> 16) & 255) >> 4, ((code >> 8) & 255) >> 4, (code & 255) >> 4)
            good += hit
            tot += n
            if len(cnt) > 1:
                coll += 1
        conf = good / tot if tot else 0.0
        shown = " ".join("--" if c is None else "%x%x%x" % c for c in pal)
        print(f"{''.join(map(str, perm))}     {coll:3d}       {conf:.4f}    {shown}")
        best.append((coll, -conf, perm, pal))
    best.sort(key=lambda t: (t[0], t[1]))
    coll, neg, perm, pal = best[0]
    print(f"\nBEST: plane order {''.join(map(str, perm))}  collisions={coll}  "
          f"confidence={-neg:.4f}")
    print("palette: " + " ".join("--" if c is None else "%x%x%x" % c for c in pal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
