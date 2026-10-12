"""Extract the *runtime* PC-98 palette out of a DOSBox-X screenshot.

The key fact
------------
DOSBox-X writes screenshots of indexed (16-colour PC-98) modes as **indexed
PNG/BMP**: the file carries a `PLTE` chunk whose entry N is the RGB that DAC
index N had on screen. That makes the screenshot a palette dump - the thing
DOSBox-X has no menu item for.

Two modes:
  * indexed screenshot (P mode, e.g. `*.raw1.png`): entry N == DAC index N.
    This is the good case - index -> RGB comes straight out of the file.
  * true-colour screenshot (RGB mode, scaled window grab): the colours are
    there but only as a set; use `pd2pal.py --shot <shot.png> --vram <Vga.bin>`
    (save state of the same screen), or reduce the window scaler to 1x first.

Usage
-----
    python tools\\pal_from_shot.py capture\\game.raw1.png -o out\\game.pal
    python tools\\pal_from_shot.py capture\\*.raw1.png --outdir out\\pal --fmt all
    python tools\\pal_from_shot.py capture\\game.raw1.png --preview out\\game.png
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path


def write_formats(path: Path, pal, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = path.with_suffix("")
    if fmt in ("jasc", "all"):
        with open(stem.with_suffix(".pal"), "w", newline="\n") as f:
            f.write("JASC-PAL\n0100\n16\n")
            for r, g, b in pal:
                f.write(f"{r * 17} {g * 17} {b * 17}\n")
    if fmt in ("raw", "all"):                       # 768 bytes, 256xRGB (Padus/ACT style)
        with open(stem.with_suffix(".rgb"), "wb") as f:
            for r, g, b in pal:
                f.write(bytes([r * 17, g * 17, b * 17]))
    if fmt in ("nibbles", "all"):                   # 48 bytes, 4-bit components
        with open(stem.with_suffix(".nib"), "wb") as f:
            for r, g, b in pal:
                f.write(bytes([r, g, b]))
    if fmt in ("bytes16", "all"):                   # 48 bytes, 8-bit components
        with open(stem.with_suffix(".b16"), "wb") as f:
            for r, g, b in pal:
                f.write(bytes([r * 17, g * 17, b * 17]))
    if fmt in ("packed", "all"):                    # the game's own 32-byte form
        out = bytearray()
        for i, (r, g, b) in enumerate(pal):
            out.append(((i & 15) << 4) | (r & 15))
            out.append(((g & 15) << 4) | (b & 15))
        with open(stem.with_suffix(".pk"), "wb") as f:
            f.write(bytes(out))
    if fmt in ("json", "all"):
        with open(stem.with_suffix(".json"), "w", encoding="utf-8") as f:
            f.write("[\n")
            f.write(",\n".join(f'  [{r}, {g}, {b}]' for r, g, b in pal))
            f.write("\n]\n")


def preview(path: Path, pal, used, cell: int = 64) -> None:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (cell * 8, cell * 4), (0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(16):
        x, y = (i % 8) * cell, (i // 8) * cell
        im.paste(Image.new("RGB", (cell - 2, cell - 2),
                           tuple(c * 17 for c in pal[i])), (x + 1, y + 1))
        if i in used:
            d.rectangle([x + 1, y + 1, x + cell - 2, y + cell - 2], outline=(255, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    print(f"  preview -> {path}  (magenta border = index actually used on screen)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shots", nargs="+")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--outdir", type=Path)
    ap.add_argument("--fmt", default="jasc", choices=["jasc", "raw", "nibbles",
                                                      "bytes16", "packed", "json", "all"])
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args()

    from PIL import Image

    files = []
    for pat in a.shots:
        got = glob.glob(pat)
        files.extend(Path(p) for p in (got or [pat]))

    for shot in files:
        im = Image.open(shot)
        print(f"\n=== {shot} ===")
        print(f"  {im.mode} {im.size[0]}x{im.size[1]}")
        if im.mode != "P":
            print("  NOT an indexed image: the file has no index -> RGB table.")
            print("  Set the window scaler to 1x / take the grab from the "
                  "unscaled path, or use `pd2pal.py --shot ... --vram Vga.bin`.")
            continue
        raw = im.getpalette() or []
        if len(raw) < 48:
            print(f"  palette has only {len(raw) // 3} entries")
            continue
        pal = []
        bad = []
        for i in range(16):
            r, g, b = raw[3 * i:3 * i + 3]
            if (r % 17) or (g % 17) or (b % 17):
                bad.append(i)
            pal.append((r // 17, g // 17, b // 17))
        used = sorted(set(im.tobytes()))
        print("  index -> RGB (nibbles)")
        for i in range(16):
            mark = " " if i in used else "*"          # * = index not used on this screen
            print(f"   {mark}[{i:2d}] {pal[i][0]:x}{pal[i][1]:x}{pal[i][2]:x}"
                  f"   rgb8=({pal[i][0] * 17:3d},{pal[i][1] * 17:3d},{pal[i][2] * 17:3d})")
        if bad:
            print(f"  WARNING: entries {bad} are not multiples of 17 - the file "
                  "was re-encoded, values may be interpolated")
        if len(set(pal)) < 16:
            print("  note: some entries are identical (normal for a game screen)")

        if a.out and len(files) == 1:
            write_formats(a.out, pal, a.fmt)
            print(f"  wrote {a.out.with_suffix('')}.*  ({a.fmt})")
        if a.outdir:
            write_formats(a.outdir / shot.stem, pal, a.fmt)
            print(f"  wrote {a.outdir / shot.stem}.*  ({a.fmt})")
        if a.preview and len(files) == 1:
            preview(a.preview, pal, set(used))
    return 0


if __name__ == "__main__":
    sys.exit(main())
