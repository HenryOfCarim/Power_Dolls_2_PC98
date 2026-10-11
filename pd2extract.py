"""Power Dolls 2 (PC-98) graphics extractor.

Usage:
    python pd2extract.py --all  <dir-with-PD2D>  <outdir>
    python pd2extract.py --pck  <archive.PCK>    <outdir>
    python pd2extract.py --ask  <file.ASK>       <outdir>
Options:
    --palette pc98|gray|vivid   (default pc98)
    --scale N                   (default 1)

Handles .ASK standalone pictures and .PCK archives.
.GCP files are NOT pictures: they are GDI/GDC display lists for the PC-98
graphics hardware (handler at CONVERT.EXE image 0x5CE2 writes I/O ports 0x7C/0x7E).
"""
import os, sys, struct, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pd2img import parse_entry, parse_archive, is_image_entry, planes_from_stream, indices_from_planes

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
    ap.add_argument('--palette', default='pc98', choices=['pc98', 'gray', 'vivid'])
    ap.add_argument('--pal', metavar='FILE.pal',
                    help='use a palette file (JASC-PAL / raw 768 / 48-byte / 16x"R G B" text)')
    ap.add_argument('--scale', type=int, default=1)
    a = ap.parse_args()
    if a.pal:
        pal = load_palette_file(a.pal)
    else:
        pal = {'pc98': PC98, 'gray': GRAY, 'vivid': VIVID}[a.palette]
    os.makedirs(a.outdir, exist_ok=True)
    n = 0

    def do(blob, name):
        nonlocal n
        try:
            r, size = one(blob, name, pal, a.scale)
            n += 1
            return True
        except Exception as e:
            print(f"  ! {name}: {e}")
            return False

    if a.ask:
        base = os.path.splitext(os.path.basename(a.ask))[0]
        blob = open(a.ask, 'rb').read()
        if not is_image_entry(blob):
            sz, x, y, w, h = struct.unpack_from('<IHHHH', blob, 0)
            print(f"{os.path.basename(a.ask)}: header does not validate "
                  f"(decoded_size={sz}, x={x}, y={y}, w={w}, h={h}) -- skipped")
            return
        do(blob, os.path.join(a.outdir, base + '.png'))
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
            stem = os.path.splitext(os.path.basename(src))[0]
            if src.upper().endswith('.ASK'):
                print(f"{os.path.basename(src)}")
                do(open(src, 'rb').read(), os.path.join(a.outdir, stem + '.png'))
            else:
                try:
                    ents = parse_archive(src)
                except Exception as e:
                    print(f"{os.path.basename(src)}: not an archive ({e})")
                    continue
                imgs = [(i, b) for i, b in ents if is_image_entry(b)]
                print(f"{os.path.basename(src)}: {len(imgs)}/{len(ents)} image entries")
                d = os.path.join(a.outdir, stem)
                os.makedirs(d, exist_ok=True)
                for i, b in imgs:
                    do(b, os.path.join(d, f"{stem}_{i:03d}.png"))
    print(f"\n{n} image(s) written to {a.outdir}")


if __name__ == '__main__':
    main()
