"""Render a DOSBox-X save-state `Vga` blob to a PNG (640x400, 16 colours).

The blob is not raw GVRAM: the plane stride is 0x10000, not the physical
0x8000, and the planes start at 0x07C000.  Getting this wrong is why early
render attempts produced noise (see docs/PITFALLS.md).

Usage:
    python tools\\render_vram.py dump\\Vga.bin out\\screen.png [--pal file.pal]
                                                             [--order 0,1,2,3]
"""
import os, sys, struct, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE, GAP, W, H, NB = 0x07C000, 0x10000, 640, 400, 80

# blob plane k -> colour bit; proven from the blit code at CONVERT.EXE 0x5B1F
DEFAULT_ORDER = (0, 1, 2, 3)


def build_indices(v, order=DEFAULT_ORDER):
    import numpy as np
    I = np.zeros((H, W), dtype=np.uint8)
    for k in range(4):
        off = BASE + k * GAP
        p = np.frombuffer(v[off:off + H * NB], dtype=np.uint8).reshape(H, NB)
        bits = np.unpackbits(p, axis=1, bitorder='big').reshape(H, NB * 8).astype(np.uint8)
        I |= bits << order[k]
    return I


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('vram')
    ap.add_argument('out')
    ap.add_argument('--pal', help='palette file (JASC/raw/48-byte/text)')
    ap.add_argument('--order', default='0,1,2,3',
                    help='blob plane k -> colour bit, e.g. "0,1,2,3"')
    a = ap.parse_args()

    from PIL import Image
    order = tuple(int(x) for x in a.order.split(','))
    v = open(a.vram, 'rb').read()
    if len(v) < BASE + 4 * GAP:
        sys.exit(f"{a.vram}: too short for the PC-98 Vga layout ({len(v)} bytes)")

    if a.pal:
        from pd2pal import read_pal
        pal = [(r * 17, g * 17, b * 17) for r, g, b in read_pal(a.pal)]
    else:
        from pd2extract import PC98 as pal

    I = build_indices(v, order)
    im = Image.new('P', (W, H))
    p = []
    for c in pal:
        p += list(c)
    p += [0] * (768 - len(p))
    im.putpalette(p)
    im.putdata(I.ravel().tolist())
    im.convert('RGB').save(a.out)
    print(f"wrote {a.out} ({W}x{H}, {len(set(I.ravel().tolist()))} distinct indices)")


if __name__ == '__main__':
    main()
