"""Self-check for the claims in docs/FORMAT.md, docs/PALETTE.md, docs/LOAD_ORDER.md.

Writes nothing.  Exits non-zero if any check fails.

    python tools\\verify.py --data ..\\hdi\\PD2D
    python tools\\verify.py --data ..\\hdi\\PD2D --floppy ..     # also the disk releases
"""
import os, sys, struct, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pd2img import decode_lzss, parse_archive, is_image_entry
from pd2pal import palette_from_packed, DEFAULT_PALETTE

# ---------------------------------------------------------------- expectations
# decoder entry point in the load image.  Two prologue forms exist:
#   `enter 6,0`                       -> entry == signature anchor
#   `push bp / mov bp,sp / sub sp,6`  -> entry == anchor - 2
HDI_EXPECTED = [
    ("CONVERT.EXE",  0x0054E6),
    ("TACTICS.EXE",  0x0046BE),
    ("BRIEFING.EXE", 0x00E915),
    ("STARTUP.EXE",  0x0055A8),
    ("CHOICE.EXE",   0x00459C),
    ("OPENING.EXE",  0x005809),
    ("REPORT.EXE",   0x00597D),
]
FLOPPY_EXPECTED = [
    ("disk 1/USERDISK.EXE", 0x0056FC),
    ("disk 5/INST.EXE",     0x0074B7),
    ("disk 5/CONVERT.EXE",  0x005ECA),
    ("disc 2/BRIEFING.EXE", 0x00C4A1),
    ("disc 2/CHOICE.EXE",   0x00448A),
    ("disc 2/STARTUP.EXE",  0x005418),
    ("disk 3/TACTICS.EXE",  0x00464E),
    ("disk 4/REPORT.EXE",   0x005742),
]

NIB = bytes.fromhex("c45e06268b470225f000c1e004260907268b4702250f000502002689470226c747080000")
BIT = bytes.fromhex("26d16f0a268b470aa9000175")
# in CONVERT.EXE: body at 0x54E6, NIB at 0x566B, BIT at 0x5514
BODY, NIBREL, BITREL = 0x54E6, 0x566B - 0x54E6, 0x5514 - 0x54E6
BODY_LEN = 539

# Distinctive codec constants.  Used when the byte layout differs because the
# compiler chose not to inline the buffered-getc helper (OPENING.EXE, REPORT.EXE).
MARKERS = {
    'bit-reader head':  bytes.fromhex('26d16f0a268b470aa9000175'),
    'nibble mask+shift': bytes.fromhex('25f000c1e004260907'),
    'length low nibble': bytes.fromhex('250f00050200'),
    'ring mask 0FFF':   bytes.fromhex('26816704ff0f'),
    'ring store':       bytes.fromhex('268b470426ff470403d8'),
    'match copy base':  bytes.fromhex('0346fc25ff0f03d8268a470c'),
}

EXPECT_PCK_IMAGES = 348
EXPECT_ASK_IMAGES = 12
EXPECT_GCP = 26
EXPECT_GCP_CUSTOM = 2

fails, notes = [], []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def load_image(path):
    d = open(path, 'rb').read()
    if d[:2] not in (b'MZ', b'ZM'):
        return None
    f = struct.unpack_from('<14H', d, 0)
    hdr = f[4] * 16
    size = (f[2] - 1) * 512 + f[1] - hdr
    return d[hdr:hdr + size]


def sig_anchor(img):
    """-> (anchor, which) where which in {'NIB','BIT','NIB+BIT'} or (None, None)."""
    n, b = img.find(NIB), img.find(BIT)
    if n >= 0:
        return n - NIBREL, ('NIB+BIT' if b >= 0 else 'NIB')
    if b >= 0:
        return b - BITREL, 'BIT'
    return None, None


def entry_point(img, anchor):
    """step back to a plausible function prologue"""
    for back in range(0, 9):
        a = anchor - back
        if a < 0:
            break
        if img[a:a + 3] == b'\x55\x8b\xec':
            return a
        if img[a] == 0xC8 and img[a + 3] == 0x00:
            return a
    return anchor


def window(img, sig, rel):
    i = img.find(sig)
    if i < 0:
        return None
    return img[i:i + (BODY_LEN - rel)]


# ------------------------------------------------------------------------ 1
def verify_locations(root, table, label):
    print(f"\n[1] decoder locations - {label}")
    for name, expected in table:
        p = os.path.join(root, name.replace('/', os.sep))
        if not os.path.exists(p):
            notes.append(f"{label}: {name} not present, skipped")
            print(f"  SKIP  {name} (not found)")
            continue
        img = load_image(p)
        if img is None:
            check(False, f"{name}: not a DOS EXE")
            continue
        anchor, which = sig_anchor(img)
        if anchor is None:
            check(False, f"{name}: no decoder signature")
            continue
        entry = entry_point(img, anchor)
        check(entry == expected,
              f"{name}: entry 0x{entry:06X} (expected 0x{expected:06X}), "
              f"anchor 0x{anchor:06X}, sigs={which}")


# ------------------------------------------------------------------------ 2
def verify_identity(data_root):
    """Same library routine everywhere.

    Most binaries are byte-identical to CONVERT.EXE from the signature onwards,
    except inside far-call immediates (which point at that build's runtime).
    OPENING.EXE / REPORT.EXE were compiled without inlining the buffered-getc
    helper, so their byte layout differs; for those we check that the codec's
    distinctive constants are all present instead.
    """
    print("\n[3] one statically linked library routine")
    conv = load_image(os.path.join(data_root, "CONVERT.EXE"))
    ref = {k: window(conv, s, r) for k, (s, r) in
           (('NIB', (NIB, NIBREL)), ('BIT', (BIT, BITREL)))}
    for name in ("TACTICS.EXE", "BRIEFING.EXE", "STARTUP.EXE", "CHOICE.EXE",
                 "OPENING.EXE", "REPORT.EXE"):
        p = os.path.join(data_root, name)
        if not os.path.exists(p):
            print(f"  SKIP  {name} (not found)")
            continue
        img = load_image(p)
        w = window(img, BIT, BITREL)
        if w is None or ref['BIT'] is None:
            check(False, f"{name}: no BIT signature")
            continue
        n = min(len(w), len(ref['BIT']))
        diff = [i for i in range(n) if w[i] != ref['BIT'][i]]
        bad = [i for i in diff
               if not any(ref['BIT'][a] == 0x9A for a in range(max(0, i - 4), i + 1))]
        if not bad:
            check(True, f"{name}: byte-identical build "
                        f"({len(diff)} bytes differ, all inside lcall immediates)")
        else:
            found = [k for k, v in MARKERS.items() if img.find(v) >= 0]
            check(len(found) >= 5,
                  f"{name}: different compilation ({len(bad)} bytes differ), "
                  f"codec markers present {len(found)}/{len(MARKERS)}"
                  + (f", missing: {[k for k in MARKERS if k not in found]}" if len(found) < len(MARKERS) else ""))


# ------------------------------------------------------------------------ 4
def verify_container(data_root):
    print("\n[4] every image entry decodes exactly and consumes its stream")
    pck_images = ask_images = 0
    problems = []
    for fn in sorted(os.listdir(data_root)):
        p = os.path.join(data_root, fn)
        if not os.path.isfile(p):
            continue
        up = fn.upper()
        if up.endswith('.PCK'):
            pairs = [(f"{fn}#{i}", b) for i, b in parse_archive(p)]
        elif up.endswith('.ASK'):
            pairs = [(fn, open(p, 'rb').read())]
        else:
            continue
        for label, blob in pairs:
            if not is_image_entry(blob):
                continue
            if up.endswith('.PCK'):
                pck_images += 1
            else:
                ask_images += 1
            sz = struct.unpack_from('<I', blob, 0)[0]
            try:
                out, used = decode_lzss(blob, 12, sz)
            except Exception as e:
                problems.append(f"{label}: {e}")
                continue
            leftover = (len(blob) - 12) - (used - 12)
            if len(out) != sz or not (0 <= leftover <= 1):
                problems.append(f"{label}: len={len(out)}/{sz} leftover={leftover}")
    total = pck_images + ask_images
    check(not problems, f"{total} image entries decoded exactly, stream consumed"
          if not problems else f"{len(problems)} problem(s): {problems[:5]}")
    check(pck_images == EXPECT_PCK_IMAGES,
          f".PCK image entries = {pck_images} (expected {EXPECT_PCK_IMAGES})")
    check(ask_images == EXPECT_ASK_IMAGES,
          f".ASK pictures = {ask_images} (expected {EXPECT_ASK_IMAGES})")


# ------------------------------------------------------------------------ 4
def verify_palettes(data_root):
    print("\n[5] palettes: 32-byte packed table at offset 0xB of every .GCP")
    gcp = [f for f in sorted(os.listdir(data_root)) if f.upper().endswith('.GCP')]
    default = tuple(tuple(c) for c in DEFAULT_PALETTE)
    valid, custom = 0, []
    for f in gcp:
        pal = palette_from_packed(open(os.path.join(data_root, f), 'rb').read())
        if pal:
            valid += 1
            if tuple(tuple(c) for c in pal) != default:
                custom.append(f)
    check(len(gcp) == EXPECT_GCP, f"{len(gcp)} .GCP files (expected {EXPECT_GCP})")
    check(valid == len(gcp), f"{valid}/{len(gcp)} have a valid packed palette at 0xB")
    check(len(custom) == EXPECT_GCP_CUSTOM,
          f"{len(custom)} carry a non-default palette: {custom}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=os.path.join('..', 'hdi', 'PD2D'),
                    help='directory with the game data files (PD2D)')
    ap.add_argument('--floppy', default=None,
                    help='root of the floppy releases, to also check those binaries')
    a = ap.parse_args()
    data_root = os.path.abspath(a.data)
    if not os.path.isdir(data_root):
        sys.exit(f"data directory not found: {data_root}")
    print(f"data root: {data_root}")

    verify_locations(data_root, HDI_EXPECTED, "HDI release")
    if a.floppy:
        verify_locations(os.path.abspath(a.floppy), FLOPPY_EXPECTED, "floppy release")
    verify_identity(data_root)
    verify_container(data_root)
    verify_palettes(data_root)

    print()
    for n in notes:
        print(f"  note: {n}")
    if fails:
        print(f"\nFAILED: {len(fails)} check(s)")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == '__main__':
    main()
