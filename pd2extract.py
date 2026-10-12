"""Power Dolls 2 (PC-98) graphics extractor.

Usage:
    python pd2extract.py --all  <dir-with-PD2D>  <outdir>
    python pd2extract.py --pck  <archive.PCK>    <outdir>
    python pd2extract.py --ask  <file.ASK>       <outdir>
Options:
    --palette pc98|gray|vivid   (default pc98)
    --pal FILE.pal              own palette file
    --pal-exe FILE.EXE:0xOFFSET a screen palette stored in an EXE, e.g.
                                BRIEFING.EXE:0x234C6 (equip artwork) or
                                TACTICS.EXE:0x1ECA4 (gameplay/tactics)
    --raw-geom WxH              geometry for a "raw block" .ASK (default: derived
                                from decoded_size, e.g. S_ROLL.ASK = 640x320)
    --scale N                   (default 1)

Handles .ASK standalone pictures and .PCK archives.
.GCP files are NOT pictures: they are GDI/GDC display lists for the PC-98
graphics hardware (handler at CONVERT.EXE image 0x5CE2 writes I/O ports 0x7C/0x7E).

A screen palette is a 48-byte table inside the game's EXEs, stored with the
channels in (B, R, G) order - see docs/PALETTE_TABLES.md and `pd2pal.py --exe`.
"""
import os
import sys
import struct
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pd2img import (parse_entry, parse_archive, is_image_entry, is_raw_block,
                    raw_geometry, planes_from_stream, indices_from_planes)
from pd2pal import (parse_exe_spec, palette_from_exe_table,
                    infer_screen_role, known_screen_palettes)

# The PC-98 default 16-colour palette, exactly as the game writes it.
# Taken from the 32-byte packed table at offset 0xB of 24 of the 26 .GCP files,
# which the writer at BRIEFING.EXE image 0x10A59 pushes to ports 0xA8/0xAA/0xAC/0xAE.
# Entries 9..15 are the "dim" half (level 10 instead of 15).
PC98 = [(0x00,0x00,0x00), (0x00,0x00,0xff), (0x00,0xff,0x00), (0x00,0xff,0xff),
        (0xff,0x00,0x00), (0xff,0x00,0xff), (0xff,0xff,0x00), (0xff,0xff,0xff),
        (0x77,0x77,0x77), (0x00,0x00,0xaa), (0x00,0xaa,0x00), (0x00,0xaa,0xaa),
        (0xaa,0x00,0x00), (0xaa,0x00,0xaa), (0xaa,0xaa,0x00), (0xaa,0xaa,0xaa)]

GRAY = [(_i * 17, _i * 17, _i * 17) for _i in range(16)]
VIVID = [(0,0,0),(0,0,170),(0,170,0),(0,170,170),(170,0,0),(170,0,170),(170,85,0),(170,170,170),
         (85,85,85),(85,85,255),(85,255,85),(85,255,255),(255,85,85),(255,85,255),(255,255,85),(255,255,255)]


def load_palette_file(path):
    """Read a .pal sidecar (JASC-PAL, raw 768-byte, 48-byte or text)."""
    from pd2pal import read_pal
    pal = read_pal(path)
    return [(r * 17, g * 17, b * 17) for r, g, b in pal]


def save_png(w, h, indices, path, palette, scale=1):
    from PIL import Image
    im = Image.new('P', (w, h))
    p = []
    for c in palette: p += list(c)
    p += [0] * (768 - len(p))
    im.putpalette(p)
    im.putdata(list(indices))
    im = im.convert('RGB')
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    im.save(path)
    return im.size


def one(blob, path, palette, scale):
    r = parse_entry(blob)
    pl = planes_from_stream(r['stream_bytes'], r['w'], r['h'])
    idx = indices_from_planes(pl, r['w'], r['h'])
    size = save_png(r['w'], r['h'], idx, path, palette, scale)
    return r, size


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--all'); g.add_argument('--pck'); g.add_argument('--ask')
    ap.add_argument('outdir')
    ap.add_argument('--palette', default='pc98', choices=['pc98', 'gray', 'vivid', 'auto'])
    ap.add_argument('--palette-dir', metavar='DIR',
                    help='directory with game EXEs for --palette auto; defaults to input directory')
    ap.add_argument('--pal', metavar='FILE.pal',
                    help='use a palette file (JASC-PAL / raw 768 / 48-byte / 16x"R G B" text)')
    ap.add_argument('--pal-exe', metavar='FILE.EXE:0xOFFSET',
                    help='use the 48-byte palette table stored in an EXE, channel order '
                         'B,R,G (e.g. BRIEFING.EXE:0x234C6, TACTICS.EXE:0x1ECA4); '
                         'list them with `pd2pal.py --exe FILE.EXE`')
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--raw-geom', metavar='WxH',
                    help='geometry for a raw-block .ASK; default derives it from '
                         'decoded_size (640x320 for S_ROLL.ASK)')
    a = ap.parse_args()
    if a.palette == 'auto' and (a.pal or a.pal_exe):
        ap.error('--palette auto cannot be combined with --pal or --pal-exe')
    if a.palette != 'auto' and a.palette_dir:
        ap.error('--palette-dir can only be used with --palette auto')
    raw_geom = None
    if a.raw_geom:
        try:
            w, _, h = a.raw_geom.lower().partition('x')
            raw_geom = (int(w), int(h))
        except ValueError:
            sys.exit(f"--raw-geom wants WxH, got {a.raw_geom!r}")
    if a.pal_exe:
        path, off = parse_exe_spec(a.pal_exe)
        if off is None:
            sys.exit("--pal-exe needs FILE.EXE:0xOFFSET "
                     "(list the offsets with `pd2pal.py --exe FILE.EXE`)")
        try:
            blob = open(path, 'rb').read()
        except OSError as e:
            sys.exit(f"{path}: {e}")
        try:
            raw, order = palette_from_exe_table(blob, off)
        except ValueError as e:
            sys.exit(f"{path}: {e}")
        pal = [(r * 17, g * 17, b * 17) for r, g, b in raw]
        note = "" if order == 'B,R,G' else f" (channel order {order})"
        if order.endswith('(unverified)'):
            note += " -- WARNING: does not look like a palette"
        print(f"palette: {os.path.basename(path)} @ {off:#x}{note}")
        if a.pal:
            print("note: --pal-exe wins over --pal")
    elif a.pal:
        pal = load_palette_file(a.pal)
    elif a.palette == 'auto':
        pal = PC98
    else:
        pal = {'pc98': PC98, 'gray': GRAY, 'vivid': VIVID}[a.palette]

    auto_palettes = {}
    if a.palette == 'auto':
        if a.palette_dir:
            palette_root = a.palette_dir
        elif a.all:
            palette_root = a.all
        else:
            source = a.pck or a.ask
            palette_root = os.path.dirname(os.path.abspath(source))
        auto_palettes = known_screen_palettes(palette_root)
        if auto_palettes:
            print(f"palette auto: found {len(auto_palettes)} known screen role(s) under {palette_root}")
        else:
            print(f"palette auto: no known screen tables under {palette_root}; using PC-98 default when no filename hint matches")
    os.makedirs(a.outdir, exist_ok=True)
    n = 0

    def palette_for(asset):
        if a.palette != 'auto':
            return pal
        role, keyword = infer_screen_role(asset)
        if not role:
            print(f"  palette auto: no filename hint for {os.path.basename(asset)}; using PC-98 default")
            return PC98
        candidate = auto_palettes.get(role)
        if candidate is None:
            print(f"  palette auto: hint {keyword!r} suggests {role}, but no matching EXE table was found; using PC-98 default")
            return PC98
        chosen, source, offset = candidate
        print(f"  palette auto: hint {keyword!r} suggests {role}; using {os.path.basename(source)} @ {offset:#x}")
        return chosen

    def do(blob, name, palette):
        nonlocal n
        try:
            r, size = one(blob, name, palette, a.scale)
            n += 1
            return True
        except Exception as e:
            print(f"  ! {name}: {e}")
            return False

    def do_ask_file(src, out_path, palette):
        """A standalone .ASK: normal 12-byte entry, or a "raw block" (S_ROLL.ASK).

        A raw block carries `u32 decoded_size` + LZSS from offset 4 and no
        geometry, so it is derived from decoded_size (or taken from --raw-geom).
        """
        nonlocal n
        blob = open(src, 'rb').read()
        if is_image_entry(blob):
            return do(blob, out_path, palette)
        raw = is_raw_block(blob)
        if raw is None:
            sz, x, y, w, h = struct.unpack_from('<IHHHH', blob, 0)
            print(f"{os.path.basename(src)}: header does not validate "
                  f"(decoded_size={sz}, x={x}, y={y}, w={w}, h={h}) -- skipped")
            return False
        geom = raw_geom or raw_geometry(len(raw))
        if geom is None:
            print(f"  ! {os.path.basename(src)}: raw block of {len(raw)} bytes "
                  f"({len(raw) * 2} px of 4-plane data) - unknown screen size, "
                  f"pass --raw-geom WxH")
            return False
        w, h = geom
        try:
            idx = indices_from_planes(planes_from_stream(raw, w, h), w, h)
            save_png(w, h, idx, out_path, palette, a.scale)
            n += 1
            print(f"{os.path.basename(src)}: raw block -> {w}x{h}")
            return True
        except Exception as e:
            print(f"  ! {out_path}: {e}")
            return False

    if a.ask:
        base = os.path.splitext(os.path.basename(a.ask))[0]
        do_ask_file(a.ask, os.path.join(a.outdir, base + '.png'), palette_for(a.ask))
    else:
        if a.all:
            srcs = []
            for root, _dirs, files in os.walk(a.all):
                for f in files:
                    if f.upper().endswith(('.PCK', '.ASK')):
                        srcs.append(os.path.join(root, f))
        else:
            srcs = [a.pck]
        for src in sorted(srcs):
            src_palette = palette_for(src)
            stem = os.path.splitext(os.path.basename(src))[0]
            # in --all mode mirror the input tree: archives with the same name in
            # different directories (the floppy release has several) would
            # otherwise overwrite each other's output
            if a.all:
                rel = os.path.relpath(os.path.dirname(os.path.abspath(src)),
                                      os.path.abspath(a.all))
                sub = '' if rel == os.curdir else rel
            else:
                sub = ''
            if src.upper().endswith('.ASK'):
                print(f"{os.path.basename(src)}")
                out_path = os.path.join(a.outdir, sub, stem + '.png')
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                do_ask_file(src, out_path, src_palette)
            else:
                try:
                    ents = parse_archive(src)
                except Exception as e:
                    print(f"{os.path.basename(src)}: not an archive ({e})")
                    continue
                imgs = [(i, b) for i, b in ents if is_image_entry(b)]
                print(f"{os.path.basename(src)}: {len(imgs)}/{len(ents)} image entries")
                d = os.path.join(a.outdir, sub, stem)
                os.makedirs(d, exist_ok=True)
                for i, b in imgs:
                    do(b, os.path.join(d, f"{stem}_{i:03d}.png"), src_palette)
    print(f"\n{n} image(s) written to {a.outdir}")


if __name__ == '__main__':
    main()
