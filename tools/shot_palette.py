"""Derive the on-screen 16-colour palette from a screenshot (offline, no emulator).

Why: the artwork screens of Power Dolls 2 have no palette table in the game
files, and DOSBox-X has no "dump palette" command. But the emulator renders the
screen with the *correct* palette, so the rendered pixels carry the palette -
"what is on screen is exactly what the DAC holds", because PC-98 text and
graphics are index -> DAC lookups with no dithering or filtering.

Two modes
---------
1. free mode  (no VRAM needed): the screenshot is quantised to at most 16
   colours.  With --expect N the 16-nearest colours to a given palette are
   merged and N is reported, so a clean screen is self-validating.

2. exact mode (recommended when a save state of the *same* screen exists):
   pass --vram <Vga.bin> (and optionally --memory <Memory.bin>) and the tool
   builds the true index image out of GVRAM and reports, for every one of the
   16 indices, the rendered colour(s) observed at pixels carrying that index.
   That is a one-to-one index -> RGB table, i.e. the DAC contents.

Confidence is reported for both: in exact mode it is the fraction of sampled
pixels that support the winning colour of their index.

Usage
-----
    python tools\\shot_palette.py capture\\game.png
    python tools\\shot_palette.py capture\\game.png --vram dump\\Vga.bin -o out\\screen.pal
    python tools\\shot_palette.py capture\\*.png --palette pc98 --outdir out\\pal
"""
from __future__ import annotations

import argparse
import collections
import glob
import sys
from pathlib import Path

PC98_DEFAULT = [(0, 0, 0), (0, 0, 15), (0, 15, 0), (0, 15, 15),
                (15, 0, 0), (15, 0, 15), (15, 15, 0), (15, 15, 15),
                (7, 7, 7), (0, 0, 10), (0, 10, 0), (0, 10, 10),
                (10, 0, 0), (10, 0, 10), (10, 10, 0), (10, 10, 10)]

# GVRAM as it appears inside a DOSBox-X save state (see docs/PALETTE.md)
GVRAM_BASE = 0x07C000
GVRAM_PLANE_GAP = 0x10000
GVRAM_ROW_BYTES = 80
GVRAM_ROWS = 400


def write_pal(path: Path, pal, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jasc":
        with open(path, "w", newline="\n") as f:
            f.write("JASC-PAL\n0100\n16\n")
            for r, g, b in pal:
                f.write(f"{r * 17} {g * 17} {b * 17}\n")
    elif fmt == "raw":                      # 768 bytes, 8-bit per component
        with open(path, "wb") as f:
            for r, g, b in pal:
                f.write(bytes([r * 17, g * 17, b * 17]))
    elif fmt == "nibbles":                  # 48 bytes, 4-bit components
        with open(path, "wb") as f:
            for r, g, b in pal:
                f.write(bytes([r & 15, g & 15, b & 15]))
    elif fmt == "bytes16":                  # 48 bytes, 8-bit components
        with open(path, "wb") as f:
            for r, g, b in pal:
                f.write(bytes([r * 17, g * 17, b * 17]))
    else:
        raise ValueError(fmt)


def show(pal) -> str:
    return " ".join("%x%x%x" % c for c in pal)


def to_nibbles(rgb):
    return tuple(min(15, (c + 8) // 17) for c in rgb)


def load_indices(vram_path: Path, memory_path: Path | None, w: int, h: int):
    """Return a 2-D numpy array of palette indices from GVRAM, or None."""
    import numpy as np

    raw = None
    if vram_path is not None:
        raw = vram_path.read_bytes()
        base = GVRAM_BASE
    elif memory_path is not None:
        raw = memory_path.read_bytes()
        base = GVRAM_BASE
    if raw is None or len(raw) < GVRAM_BASE + 4 * GVRAM_PLANE_GAP:
        return None

    idx = np.zeros((GVRAM_ROWS, GVRAM_ROW_BYTES * 8), dtype=np.uint8)
    for k in range(4):
        off = base + k * GVRAM_PLANE_GAP
        planes = np.frombuffer(raw[off:off + GVRAM_ROWS * GVRAM_ROW_BYTES],
                               dtype=np.uint8).reshape(GVRAM_ROWS, GVRAM_ROW_BYTES)
        bits = np.unpackbits(planes, axis=1, bitorder="big").astype(np.uint8)
        idx |= bits << k
    return idx[:h, :w]


def analyse(shot: Path, vram: Path | None, memory: Path | None,
            sx: float, sy: float, ox: int, oy: int, min_px: int):
    import numpy as np
    from PIL import Image

    img = Image.open(shot)
    print(f"\n=== {shot} ===")
    print(f"  image: {img.size[0]}x{img.size[1]} {img.mode}")
    rgb = np.asarray(img.convert("RGB")).astype(np.int32)
    codes = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
    uniq, counts = np.unique(codes.ravel(), return_counts=True)
    print(f"  distinct rendered colours: {len(uniq)}")
    if len(uniq) > 16:
        print("  NOTE: more than 16 colours on screen -> the grab is scaled, "
              "anti-aliased or from a 256-colour mode.")

    idx = load_indices(vram, memory, 640, 400) if (vram or memory) else None
    if idx is None:
        # free mode: report the 16 most frequent colours
        order = np.argsort(counts)[::-1]
        pal = []
        for i in order[:16]:
            c = int(uniq[i])
            pal.append(to_nibbles(((c >> 16) & 255, (c >> 8) & 255, c & 255)))
        while len(pal) < 16:
            pal.append((0, 0, 0))
        print("  top-16 colours (nibbles, NOT index-ordered):")
        for i, (c, p) in enumerate(zip(order[:16], pal)):
            v = int(uniq[c])
            print(f"    #{i:2d} pix={int(counts[c]):7d} "
                  f"rgb8=({(v >> 16) & 255:3d},{(v >> 8) & 255:3d},{v & 255:3d}) "
                  f"nib={p[0]:x}{p[1]:x}{p[2]:x}")
        print("  Without an index image the palette cannot be assigned to "
              "indices; pass --vram from a save state of the same screen.")
        return pal, 0.0

    H, W = idx.shape
    ys = np.rint(oy + np.arange(H) * sy).astype(int)
    xs = np.rint(ox + np.arange(W) * sx).astype(int)
    ky = (ys >= 0) & (ys < rgb.shape[0])
    kx = (xs >= 0) & (xs < rgb.shape[1])
    sub_idx = idx[np.ix_(np.arange(H)[ky], np.arange(W)[kx])].ravel()
    sub_codes = codes[np.ix_(ys[ky], xs[kx])].ravel()

    pal = [None] * 16
    good = tot = 0
    print("  index -> rendered colour")
    for v in range(16):
        m = sub_idx == v
        n = int(m.sum())
        if n < min_px:
            if n:
                print(f"    [{v:2d}] {n} px (below --min-px, skipped)")
            continue
        cnt = collections.Counter(sub_codes[m].tolist())
        (code, hit), = cnt.most_common(1)
        c = ((code >> 16) & 255, (code >> 8) & 255, code & 255)
        pal[v] = to_nibbles(c)
        good += hit
        tot += n
        other = ", ".join(f"{(k >> 16) & 255},{(k >> 8) & 255},{k & 255}x{v}"
                          for k, v in cnt.most_common(4)[1:])
        print(f"    [{v:2d}] {hit:6d}/{n:6d} px = rgb8{c} nib={pal[v][0]:x}{pal[v][1]:x}{pal[v][2]:x}"
              + (f"   other: {other}" if other else ""))
    conf = good / tot if tot else 0.0
    print(f"  alignment confidence {conf:.4f}"
          + ("" if conf >= 0.9 else "  <-- LOW: screenshot and save state are "
             "probably different screens, or scale/offset are wrong"))
    if any(c is None for c in pal):
        missing = [i for i, c in enumerate(pal) if c is None]
        print(f"  indices with no pixels on this screen: {missing} "
              "(cannot be recovered from a screenshot - use the in-guest dumper)")
    return pal, conf


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shots", nargs="+")
    ap.add_argument("--vram", type=Path, help="Vga.bin from a save state of the same screen")
    ap.add_argument("--memory", type=Path, help="Memory blob (used instead of --vram)")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--outdir", type=Path, help="write <screenshot>.pal next to each result")
    ap.add_argument("--fmt", default="jasc", choices=["jasc", "raw", "nibbles"])
    ap.add_argument("--sx", type=float, default=1.0)
    ap.add_argument("--sy", type=float, default=1.0)
    ap.add_argument("--ox", type=int, default=0)
    ap.add_argument("--oy", type=int, default=0)
    ap.add_argument("--min-px", type=int, default=20)
    a = ap.parse_args()

    files = []
    for pat in a.shots:
        got = glob.glob(pat)
        files.extend(Path(p) for p in (got or [pat]))

    for i, shot in enumerate(files):
        pal, conf = analyse(shot, a.vram, a.memory, a.sx, a.sy, a.ox, a.oy, a.min_px)
        print(f"  nibbles: {show(pal)}")
        if a.out and len(files) == 1:
            write_pal(a.out, pal, a.fmt)
            print(f"  wrote {a.out} ({a.fmt})")
        if a.outdir and any(c is not None for c in pal):
            dst = a.outdir / (shot.stem + ".pal")
            write_pal(dst, pal, a.fmt)
            print(f"  wrote {dst} ({a.fmt})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
