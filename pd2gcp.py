"""Power Dolls 1 / 2 (PC-98, Kogado) — GDC display lists (`.GCP`, `CHARA.PCK`) -> PNG.

`.GCP` files and 27 of the 38 `CHARA.PCK` entries are not rasters.  They are
command streams that drive the PC-98 **GRCG** (Graphic Charger, I/O ports
`0x7C` / `0x7E`) and are finished off by a row-XOR decode pass.  The model below
is read out of `CONVERT.EXE` (identical code in 10 binaries of both games):

    loader      image 0x5DE5   header, palette, GRCG seed, fill and XOR passes
    player A    image 0x5FCD   when (flags & 0x70) != 0x40
    player B    image 0x63E3   when (flags & 0x70) == 0x40
    tile helper image 0x613E / 0x6486   four bytes -> the GRCG tile registers
    byte reader image 0x6213   verbatim while flag 0x40 is set (every shipped
                               display list); otherwise a Huffman reader whose
                               table builder (image 0x6306) is wired to other
                               tables, so that path is dead for this data

Block layout
------------
    +0      flags
              bit 0x40  stream is stored verbatim
              bit 0x80  GRCG read-modify-write (XOR) tile mode
              bits 0x30 0 = plain draw; otherwise the row fill runs and the
                        row-XOR pass is applied (flags & 0x30) >> 4 times
              bits 0x0F GRCG plane mask; a SET bit means the plane is *not*
                        written, so the stream carries tile bytes only for the
                        planes whose bit is clear
    +1      width, in bytes (the row extent of the fill and of the XOR pass)
    +2..3   height, in rows (16-bit little endian)
    +4..7   the GRCG seed tile: one byte per written plane, in B,R,G,E order
    +8      payload offset, counted from +9; >= 0x22 means the 32-byte palette
            sits at +0xB and the stream starts after it
    +9..10  an optional 16-bit VRAM offset; the loader uses it instead of the
            caller's pen when the caller passes a pen >= 0x7D00
    +0xB..  the 16-colour packed palette, when +8 >= 0x22:
            byte[2i] = (index << 4) | R, byte[2i+1] = (G << 4) | B
    stream  block + 9 + block[8]

Command stream (the value the CPU writes to VRAM is irrelevant - the GRCG
replaces it with the tile, which is why the game uses a don't-care byte):

    < 0x7D   skip  = (c << 8) | next ; then stamp one byte
    0x80..   skip  = c - 0x80        ; then stamp one byte
    0x7D     count = ((d << 8) | next) + 2, or (d - 0x80) + 2 when d >= 0x80;
             stamp the current tile `count` times
    0x7E     pen = base; read a fresh tile (one stream byte per written plane)
    0x7F     pen = base; the first one switches to the second pass, in which
             every stamp is preceded by a fresh tile, the second one ends the
             block

A "stamp" writes the four tile bytes at the current VRAM offset, one byte per
written plane, and advances the offset by one - i.e. eight pixels.

Usage
-----
    python pd2gcp.py --gcp hdi/PD2D/KOGADO.GCP out
    python pd2gcp.py --pck hdi/PD2D/CHARA.PCK out --entry 3
    python pd2gcp.py --all hdi/PD2D out
    python pd2gcp.py --all "power dolls 1/_unpacked" out --pal my.pal
    python pd2gcp.py --all hdi/PD2D out --dump --list
    python pd2gcp.py --self-test

Options
    --pal FILE.pal            palette for blocks that carry none (PD1 `.GCP`)
    --pal-exe FILE.EXE:0xOFF  use a 48-byte screen palette from an EXE
    --full                    keep the declared width x height region instead of
                              cropping to the drawn bytes
    --no-xor                  stop after the display list (the raw delta mask)
    -e/--entry N              one entry of a `.PCK`
    --dump                    also write `<image>.txt`, the decoded command list
    --list                    print a table of the blocks that were found
    --scale N                 integer upscale (nearest neighbour)
    --self-test               verify the model, write nothing
"""
import argparse
import os
import struct
import sys

from pd2img import parse_archive
from pd2pal import DEFAULT_PALETTE, palette_from_exe_table, palette_from_packed, read_pal

__all__ = ["parse_header", "is_display_list", "decode", "indices", "render",
           "disassemble", "tile_order", "GRCG_PLANES"]

PLANE_SIZE = 0x8000          # the game addresses 0x8000 bytes per VRAM plane
ROW_STRIDE = 80              # 640 pixels, one VRAM row
GRCG_PLANES = ("B", "R", "G", "E")
MAX_HEIGHT = 1024


class DisplayListError(Exception):
    pass


def tile_order(flags):
    """Indices of the planes the stream supplies tile bytes for.

    The GRCG plane mask (flag bits 0..3) marks planes that are *not* touched, so
    the tile bytes cover the complement - two bytes for a 2-plane sprite, four
    for a normal picture.
    """
    return [p for p in range(4) if not (flags & (1 << p))]


def parse_header(blob):
    """Decode a display-list block header (see the module docstring)."""
    if len(blob) < 12:
        raise DisplayListError(f"block too short ({len(blob)} bytes)")
    flags = blob[0]
    start = 9 + blob[8]
    if start >= len(blob):
        raise DisplayListError(f"payload offset {blob[8]} leaves no stream")
    pal = None
    if blob[8] >= 0x22:
        pal = palette_from_packed(blob)
    return {
        "flags": flags,
        "planes": tile_order(flags),
        "width": blob[1],
        "height": blob[2] | (blob[3] << 8),
        "tile": list(blob[4:8]),
        "payload": blob[8],
        "vram_offset": blob[9] | (blob[10] << 8),
        "palette": pal,
        "start": start,
        "stream": len(blob) - start,
        "raw": bool(flags & 0x40),
        "xor_mode": bool(flags & 0x80),
        "xor_passes": (flags & 0x30) >> 4,
        "fill": bool(flags & 0x30),
    }


def is_display_list(blob):
    """Heuristic: a display-list block rather than a raster entry or other data."""
    try:
        h = parse_header(blob)
    except DisplayListError:
        return False
    return (h["raw"] and 0 < h["height"] <= MAX_HEIGHT and 0 < h["width"] <= ROW_STRIDE
            and blob[-1] == 0x7F)


def decode(blob, base=0, xor=True, limit=2_000_000):
    """Run the loader + player + row-XOR pass.  Returns a result dict.

    `base` is the VRAM byte offset the caller hands the loader (0 = the top left
    of the screen).  `xor=False` stops after the display list, which leaves the
    row-delta mask visible.
    """
    h = parse_header(blob)
    flags, planes = h["flags"], h["planes"]
    if not h["raw"]:
        raise DisplayListError("compressed display lists are not supported "
                               "(no shipped block uses that path)")
    width, height = h["width"], h["height"]
    stream = blob[h["start"]:]
    out = [bytearray(PLANE_SIZE) for _ in range(4)]
    touched = set()

    def put(off, tile):
        if 0 <= off < PLANE_SIZE:
            touched.add(off)
            for p in planes:
                out[p][off] = tile[p]

    tile = [0, 0, 0, 0]
    for i, p in enumerate(planes):
        tile[p] = h["tile"][i]

    # loader, step 1: fill `width` bytes at the start of every row with the seed
    if h["fill"]:
        for r in range(height):
            for j in range(width):
                put(base + r * ROW_STRIDE + j, tile)

    pos = 0
    n = len(stream)

    def load_tile():
        nonlocal pos
        t = [0, 0, 0, 0]
        for p in planes:
            t[p] = stream[pos] if pos < n else 0
            pos += 1
        return t

    pen = base
    tile = load_tile()
    phase = 0
    commands = []
    steps = 0
    while pos < n and steps < limit:
        steps += 1
        c = stream[pos]
        pos += 1
        if c == 0x7F:
            pen = base
            commands.append(("end", None, None) if phase else ("phase2", None, None))
            if phase:
                break
            phase = 1
            continue
        if c == 0x7E:
            pen = base
            tile = load_tile()
            commands.append(("tile", None, tile[:]))
            continue
        if c == 0x7D:
            d = stream[pos] if pos < n else 0
            pos += 1
            if d < 0x7D:
                cnt = ((d << 8) | (stream[pos] if pos < n else 0)) + 2
                pos += 1
            else:
                cnt = (d - 0x80) + 2
            commands.append(("fill", cnt, pen))
            for _ in range(cnt):
                put(pen, tile)
                pen += 1
            continue
        if c >= 0x80:
            skip = c - 0x80
        else:
            skip = (c << 8) | (stream[pos] if pos < n else 0)
            pos += 1
        pen += skip
        if phase:
            tile = load_tile()
        commands.append(("write", 1, pen))
        put(pen, tile)
        pen += 1
    if not commands or commands[-1][0] != "end":
        raise DisplayListError(
            f"stream not terminated: {pos}/{n} bytes consumed (no closing 0x7F)")

    # loader, step 2: the row-XOR decode pass, once per (flags & 0x30) >> 4
    if xor:
        for _ in range(h["xor_passes"]):
            for r in range(height - 1):
                o = base + r * ROW_STRIDE
                for j in range(width):
                    touched.add(o + ROW_STRIDE + j)
                    for p in planes:
                        out[p][o + ROW_STRIDE + j] ^= out[p][o + j]

    rows = [i // ROW_STRIDE for i in touched] or [0]
    cols = [i % ROW_STRIDE for i in touched] or [0]
    return {
        "header": h,
        "planes": out,
        "planes_used": planes,
        "touched": touched,
        "commands": commands,
        "consumed": pos,
        "stream": n,
        "row_range": (min(rows), max(rows)),
        "col_range": (min(cols), max(cols)),
        "base": base,
    }


def _indices(result, row0, row1, col0, col1, base_row):
    """Plane bytes -> one palette index per pixel (4 bpp, MSB = leftmost pixel)."""
    planes = result["planes"]
    used = result["planes_used"]
    w = (col1 - col0 + 1) * 8
    out = bytearray(w * (row1 - row0 + 1))
    for y in range(row0, row1 + 1):
        base = (y - row0) * w
        for cb in range(col0, col1 + 1):
            o = (y - base_row) * ROW_STRIDE + cb
            vals = [planes[p][o] if p in used else 0 for p in range(4)]
            for bit in range(8):
                idx = 0
                for p in range(4):
                    idx |= ((vals[p] >> (7 - bit)) & 1) << p
                out[base + (cb - col0) * 8 + bit] = idx
    return out, w


def _crop(res, base, full):
    h = res["header"]
    base_row = base // ROW_STRIDE
    if full:
        row0 = base_row
        row1 = base_row + max(0, h["height"] - 1)
        col0 = 0
        col1 = min(ROW_STRIDE - 1, max(0, h["width"] - 1))
    else:
        row0 = max(res["row_range"][0], base_row)
        row1 = res["row_range"][1]
        col0, col1 = res["col_range"]
    return row0, row1, col0, col1


def indices(blob, base=0, xor=True, full=False):
    """-> (width, height, one palette index per pixel) for a display list.

    The index buffer depends only on the block, not on the palette, so a sweep
    over many palettes decodes once and re-colours many times.
    """
    res = decode(blob, base=base, xor=xor)
    row0, row1, col0, col1 = _crop(res, base, full)
    data, w = _indices(res, row0, row1, col0, col1, base // ROW_STRIDE)
    return w, row1 - row0 + 1, data


def render(blob, base=0, palette=None, full=False, xor=True):
    """-> (PIL.Image, result dict).  `palette` is 16 (R,G,B) triples, 0..15."""
    from PIL import Image
    res = decode(blob, base=base, xor=xor)
    h = res["header"]
    pal = palette or h["palette"] or DEFAULT_PALETTE
    base_row = base // ROW_STRIDE
    row0, row1, col0, col1 = _crop(res, base, full)
    data, w = _indices(res, row0, row1, col0, col1, base_row)
    img = Image.new("P", (w, row1 - row0 + 1))
    img.putpalette([c * 17 for rgb in pal for c in rgb][:768] +
                   [0] * (768 - 48))
    img.putdata(data)
    return img.convert("RGB"), res


def disassemble(blob, base=0, limit=200000):
    """The decoded command stream as text lines."""
    res = decode(blob, base=base, xor=False)
    h = res["header"]
    lines = [f"flags {h['flags']:#04x}  planes {'/'.join(GRCG_PLANES[p] for p in h['planes'])}"
             f"  width {h['width']} bytes  height {h['height']} rows"
             f"  xor-passes {h['xor_passes']}  seed tile "
             f"{' '.join(f'{b:02x}' for b in h['tile'])}",
             f"stream {h['start']:#06x}..{len(blob):#06x} ({h['stream']} bytes), "
             f"palette {'yes' if h['palette'] else 'no'}, base {base:#06x}"]
    for i, (op, count, pen) in enumerate(res["commands"]):
        if i >= limit:
            lines.append(f"... {len(res['commands']) - limit} more commands")
            break
        if op == "write":
            lines.append(f"{i:7d}  stamp 1 @ {pen:#06x}")
        elif op == "fill":
            lines.append(f"{i:7d}  stamp {count} @ {pen:#06x}")
        elif op == "tile":
            lines.append(f"{i:7d}  tile  " + " ".join(f"{b:02x}" for b in pen))
        elif op == "phase2":
            lines.append(f"{i:7d}  --- second pass (fresh tile per stamp) ---")
        elif op == "end":
            lines.append(f"{i:7d}  end")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ file walkers
def iter_blocks(path):
    """-> (index or None, blob) for a .GCP or for every entry of a .PCK."""
    if path.lower().endswith(".pck"):
        for i, blob in parse_archive(path):
            yield i, blob
    else:
        with open(path, "rb") as f:
            yield None, f.read()


def find_display_lists(root, entry=None):
    """Walk a directory tree -> [(path, index, blob)] of display-list blocks."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            if not fn.upper().endswith((".GCP", ".PCK")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                for i, blob in iter_blocks(p):
                    if entry is not None and i != entry:
                        continue
                    if is_display_list(blob):
                        out.append((p, i, blob))
            except Exception:
                continue
    return out


# ------------------------------------------------------------------------ CLI
def _load_palette(args):
    if args.pal:
        return read_pal(args.pal)
    if args.pal_exe:
        spec = args.pal_exe
        for sep in ("@", ":"):
            if sep in spec:
                path, off = spec.rsplit(sep, 1)
                break
        else:
            raise SystemExit("--pal-exe wants FILE.EXE:0xOFFSET")
        blob = open(path, "rb").read()
        pal, _order = palette_from_exe_table(blob, int(off, 0))
        return pal
    return None


def _self_test():
    """Structural self-check: a hand-built block plus the terminator invariant."""
    # block: flags 0x40 (verbatim, all planes, no XOR), width 2, height 1
    tile = bytes([0x0F, 0x33, 0x55, 0xFF])
    stream = tile + bytes([0x80, 0x7F, 0x7F])
    blob = bytes([0x40, 2, 1, 0]) + bytes([0, 0, 0, 0]) + bytes([0]) + stream
    res = decode(blob)
    for p in range(4):
        got = res["planes"][p][0]
        assert got == tile[p], f"plane {p}: {got:#04x} != {tile[p]:#04x}"
    assert res["consumed"] == res["stream"], "hand-built block not fully consumed"

    # the same block with the seed tile fill and one XOR decode pass
    blob2 = bytes([0x50, 2, 2, 0]) + bytes([0xAA, 0, 0, 0]) + bytes([0]) + \
        bytes([0, 0, 0, 0, 0x7F, 0x7F])
    raw2 = decode(blob2, xor=False)
    assert raw2["planes"][0][0] == 0xAA and raw2["planes"][0][1] == 0xAA, \
        "seed fill did not land on the first row"
    assert raw2["planes"][0][80] == 0xAA and raw2["planes"][0][81] == 0xAA, \
        "seed fill is not `width` bytes wide on every row"
    assert raw2["planes"][0][2] == 0x00, "seed fill overran `width`"
    xored = decode(blob2)
    assert xored["planes"][0][80] == 0 and xored["planes"][0][81] == 0, \
        "the row XOR pass did not fold row 0 into row 1"

    # a truncated stream must be reported, not silently accepted
    bad = bytes([0x40, 2, 1, 0]) + bytes(4) + bytes([0]) + tile
    try:
        decode(bad)
    except DisplayListError:
        pass
    else:
        raise AssertionError("a stream without its second 0x7F was accepted")
    print("self-test: OK")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--gcp", metavar="FILE")
    src.add_argument("--pck", metavar="FILE")
    src.add_argument("--all", metavar="DIR")
    src.add_argument("--self-test", action="store_true")
    ap.add_argument("out", nargs="?", help="output directory")
    ap.add_argument("-e", "--entry", type=int, help="one .PCK entry")
    ap.add_argument("--pal", metavar="FILE.pal")
    ap.add_argument("--pal-exe", metavar="FILE.EXE:0xOFF")
    ap.add_argument("--full", action="store_true",
                    help="keep the declared width x height region")
    ap.add_argument("--no-xor", action="store_true",
                    help="stop before the row-XOR decode (shows the delta mask)")
    ap.add_argument("--dump", action="store_true", help="also write <name>.txt")
    ap.add_argument("--list", action="store_true", help="print the blocks found")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--base", type=lambda v: int(v, 0), default=0,
                    help="VRAM byte offset the caller passes the loader")
    a = ap.parse_args()

    if a.self_test:
        _self_test()
        return

    if a.gcp:
        idx, blob = next(iter_blocks(a.gcp))
        todo = [(a.gcp, idx, blob)]
    elif a.pck:
        todo = [(a.pck, i, b) for i, b in iter_blocks(a.pck)]
    elif a.all:
        todo = find_display_lists(a.all, None)
        if not todo:
            sys.exit(f"{a.all}: no display lists found")
    else:
        ap.error("one of --gcp / --pck / --all / --self-test is required")

    if not a.out:
        ap.error("an output directory is required")
    palette = _load_palette(a)
    os.makedirs(a.out, exist_ok=True)

    # a .PCK gets a subdirectory of its own, exactly like pd2extract.py
    grouped = a.pck is not None or a.all is not None
    archive_of = {}
    if grouped:
        for p, _i, _b in todo:
            archive_of[p] = os.path.splitext(os.path.basename(p))[0]

    ok = skipped = 0
    for path, index, blob in todo:
        if index is not None and a.entry is not None and index != a.entry:
            continue
        name = os.path.splitext(os.path.basename(path))[0]
        if index is not None:
            name = f"{name}_{index:03d}"
        if not is_display_list(blob):
            skipped += 1
            continue
        rel = archive_of.get(path, "") if index is not None else ""
        try:
            img, res = render(blob, base=a.base, palette=palette,
                              full=a.full, xor=not a.no_xor)
        except DisplayListError as e:
            print(f"{name}: skipped ({e})")
            skipped += 1
            continue
        if a.scale > 1:
            from PIL import Image
            img = img.resize((img.width * a.scale, img.height * a.scale), Image.NEAREST)
        dst = os.path.join(a.out, rel, name + ".png")
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        img.save(dst)
        h = res["header"]
        if a.list:
            print(f"{name:24s} {img.width:4d}x{img.height:<4d} flags={h['flags']:#04x} "
                  f"planes={''.join(GRCG_PLANES[p] for p in h['planes']) or '-':4s} "
                  f"decl={h['width']}x{h['height']} xor={h['xor_passes']} "
                  f"pal={'file' if h['palette'] else ('given' if palette else 'default')} "
                  f"stream={h['stream']} consumed={res['consumed']}")
        if a.dump:
            with open(os.path.join(a.out, rel, name + ".txt"), "w",
                      encoding="utf-8") as f:
                f.write(disassemble(blob, base=a.base))
        ok += 1
    if not a.list:
        print(f"{ok} display list(s) -> {a.out}" +
              (f"  ({skipped} skipped)" if skipped else ""))


if __name__ == "__main__":
    main()
