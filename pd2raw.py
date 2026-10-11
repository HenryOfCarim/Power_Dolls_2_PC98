"""Power Dolls 2 (PC-98) - raw block unpacker.

A third container form, used by every `.SLD` and by `S_ROLL.ASK`:

    offset 0   u32 decoded_size
    offset 4   ... LZSS stream ...

This is the same codec as `pd2img.decode_lzss`; only the container differs.
`S_ROLL.ASK` is a 640x320 frame (decoded_size = 102400) and is NOT corrupt -
it simply does not use the 12-byte picture header.

Usage:
    python pd2raw.py --file HUNIT.SLD -o out.bin
    python pd2raw.py --all  ..\\hdi\\PD2D -o out\\unpacked
"""
import os, sys, struct, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pd2img import decode_lzss

MIN_SIZE = 16
MAX_SIZE = 8_000_000


def is_raw_block(blob):
    """True if blob looks like 'u32 decoded_size' + LZSS from offset 4."""
    if len(blob) < MIN_SIZE:
        return None
    n = struct.unpack_from('<I', blob, 0)[0]
    if not (MIN_SIZE <= n <= MAX_SIZE):
        return None
    try:
        out, used = decode_lzss(blob, 4, n)
    except Exception:
        return None
    # the decisive test: the stream must be consumed to the last byte
    if len(out) == n and used >= len(blob) - 1:
        return out
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--file', metavar='FILE')
    g.add_argument('--all', metavar='DIR')
    ap.add_argument('-o', '--out', required=True,
                    help='output file (--file) or directory (--all)')
    a = ap.parse_args()

    if a.file:
        blob = open(a.file, 'rb').read()
        out = is_raw_block(blob)
        if out is None:
            sys.exit(f"{a.file}: not a raw block (u32 + LZSS @ 4)")
        with open(a.out, 'wb') as f:
            f.write(out)
        print(f"{os.path.basename(a.file)}: {len(blob)} -> {len(out)} bytes -> {a.out}")
        return

    os.makedirs(a.out, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(a.all)):
        p = os.path.join(a.all, fn)
        if not os.path.isfile(p):
            continue
        blob = open(p, 'rb').read()
        out = is_raw_block(blob)
        if out is None:
            continue
        dst = os.path.join(a.out, fn + '.bin')
        with open(dst, 'wb') as f:
            f.write(out)
        print(f"  {fn:16s} {len(blob):7d} -> {len(out):8d}  -> {dst}")
        n += 1
    print(f"{n} raw block(s) unpacked to {a.out}")


if __name__ == '__main__':
    main()
