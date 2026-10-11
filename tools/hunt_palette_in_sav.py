"""Hunt for the PC-98 palette table inside DOSBox-X save states.

Rationale
---------
The game programs the palette from a 32-byte packed table (see docs/PALETTE.md):

    byte[2i]   = (index << 4) | R
    byte[2i+1] =  G << 4      | B

That table is *data* (in the .GCP loader, in DGROUP, on the stack - somewhere),
so even though the emulator's DAC state is not serialised, the table may still
be sitting in `Memory` at the moment the state was saved.

This scans a save state (plain .sav ZIP or a raw Memory/Vga blob) for

  * candidate 32-byte packed tables (high nibble of the even byte == index), and
  * exact occurrences of the known tables from the game's .GCP files,

and prints every hit with its offset and decoded palette. A hit that is an
exact copy of a known .GCP table is proof that the palette *can* be read out of
a save state without touching the running emulator.

Usage
-----
    python tools\\hunt_palette_in_sav.py STATE.sav [STATE2.sav ...]
    python tools\\hunt_palette_in_sav.py --blob dump/Memory.bin
    python tools\\hunt_palette_in_sav.py STATE.sav --pal-dir "..\\power dolls 2 HDI\\_unpacked\\PD2D"
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

DEFAULT_PALETTE = [(0, 0, 0), (0, 0, 15), (0, 15, 0), (0, 15, 15),
                   (15, 0, 0), (15, 0, 15), (15, 15, 0), (15, 15, 15),
                   (7, 7, 7), (0, 0, 10), (0, 10, 0), (0, 10, 10),
                   (10, 0, 0), (10, 0, 10), (10, 10, 0), (10, 10, 10)]


def packed(pal) -> bytes:
    out = bytearray()
    for i, (r, g, b) in enumerate(pal):
        out.append(((i & 15) << 4) | (r & 15))
        out.append(((g & 15) << 4) | (b & 15))
    return bytes(out)


def gcp_palette(blob: bytes):
    """32-byte packed palette at 0xB of a .GCP / CHARA.PCK entry, or None."""
    if len(blob) < 0x0B + 32:
        return None
    out = []
    for i in range(16):
        b0 = blob[0x0C + 2 * i]
        b1 = blob[0x0B + 2 * i]
        if (b0 >> 4) != i:
            return None
        out.append((b0 & 15, b1 >> 4, b1 & 15))
    return out


def show(pal) -> str:
    return " ".join("%x%x%x" % c for c in pal)


def blobs_from_sav(path: Path):
    """Yield (label, bytes) for a save state / raw blob."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower() in ("memory", "vga", "vram", "gvram"):
                    yield name, z.read(name)
    else:
        yield path.name, path.read_bytes()


def find_exact(data: bytes, needle: bytes):
    out = []
    start = 0
    while True:
        i = data.find(needle, start)
        if i < 0:
            return out
        out.append(i)
        start = i + 1


def find_candidates(data: bytes, limit=64):
    """Offsets of 32-byte blocks that look like a packed palette table."""
    hits = []
    for off in range(0, max(0, len(data) - 32)):
        ok = True
        for i in range(16):
            if (data[off + 2 * i] >> 4) != i:
                ok = False
                break
        if not ok:
            continue
        pal = tuple((data[off + 2 * i] & 15, data[off + 2 * i + 1] >> 4,
                     data[off + 2 * i + 1] & 15) for i in range(16))
        hits.append((off, pal))
        if len(hits) >= limit:
            break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("states", nargs="*", type=Path)
    ap.add_argument("--blob", nargs="*", type=Path, default=[])
    ap.add_argument("--pal-dir", type=Path, default=None,
                    help="directory with .GCP files to use as known palettes")
    ap.add_argument("--max-candidates", type=int, default=8)
    a = ap.parse_args()

    known = {"pc98 default (.GCP x24)": packed(DEFAULT_PALETTE)}
    if a.pal_dir and a.pal_dir.is_dir():
        for gcp in sorted(a.pal_dir.glob("*.GCP")):
            pal = gcp_palette(gcp.read_bytes())
            if pal:
                known[f"{gcp.name}"] = packed(pal)

    targets = list(a.states) + list(a.blob)
    if not targets:
        ap.error("give at least one save state or --blob")

    for path in targets:
        print(f"\n=== {path} ===")
        for label, data in blobs_from_sav(path):
            print(f"  blob {label!r}: {len(data)} bytes")
            for name, needle in known.items():
                offs = find_exact(data, needle)
                if offs:
                    print(f"    EXACT MATCH of {name} at "
                          + ", ".join(f"0x{o:X} (lin)" for o in offs[:8])
                          + (f" ... {len(offs)} total" if len(offs) > 8 else ""))
                    print(f"      {show(gcp_palette(needle) or DEFAULT_PALETTE)}")
            cands = find_candidates(data)
            print(f"    structural candidates (byte[2i]>>4 == i): {len(cands)}"
                  + (" (capped)" if len(cands) >= a.max_candidates else ""))
            for off, pal in cands[:a.max_candidates]:
                tag = ""
                for name, needle in known.items():
                    if needle == packed(pal):
                        tag = f"   <-- identical to {name}"
                print(f"      0x{off:08X}  {show(pal)}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
