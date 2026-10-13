"""Self-check for the claims in docs/FORMAT.md, docs/PALETTE.md, docs/LOAD_ORDER.md.

Writes nothing.  Exits non-zero if any check fails.

    python tools\\verify.py --data ..\\hdi\\PD2D
    python tools\\verify.py --data ..\\hdi\\PD2D --floppy ..     # also the disk releases
"""
import os, sys, struct, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pd2img import (decode_lzss, parse_archive, is_image_entry, is_raw_block,
                    raw_geometry)
from pd2pal import (palette_from_packed, palette_to_packed, palette_from_exe_table,
                    DEFAULT_PALETTE)
from pd2gcp import (DisplayListError, decode as decode_displaylist, is_display_list,
                    parse_header)

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

# Screen palettes: 48-byte tables inside the EXEs, channel order B,R,G.
# These four were matched 16/16 against live dumps from DOSBox-X; they are what
# replaced the old (wrong) claim that the screens' palettes are nowhere in the
# files.  See docs/PALETTE_TABLES.md and tools/pal_tables.py.
EXPECT_EXE_PALETTES = [
    ("BRIEFING.EXE", 0x0234C6, "000 fdb fb8 b85 f77 68b 378 ddd 999 666 751 b55 cb8 575 fc7 fff"),
    ("STARTUP.EXE",  0x009311, "000 fdb eb8 b84 e66 57b 249 ddd 999 555 753 431 0c9 493 fd7 fff"),
    ("PD2SHELL.EXE", 0x0098E6, "000 972 c84 eb6 a55 38c 457 ddd 999 666 444 436 0c8 483 325 fff"),
    ("TACTICS.EXE",  0x01ECA4, "000 555 999 ddd f65 77f 04b fff fc8 ea6 a74 150 284 3a4 751 fdb"),
]
EXPECT_TABLES_IN_DATA = 44       # palette tables in the HDI PD2D directory

# Display lists (GDC / GRCG command streams): every .GCP in the HDI data dir and
# 27 of the 38 CHARA.PCK entries.  The decisive check is that the player stops on
# the closing 0x7F exactly when the block runs out of bytes - the same
# "consumed to the last byte" argument that validates the raster codec.
EXPECT_DISPLAYLIST_PCK = 27
EXPECT_DISPLAYLIST_GEOMETRY = [
    ("KOGADO.GCP", 24, 56),      # .GCP with a custom artwork palette
    ("K_BLANC1.GCP", 48, 112),   # no fill, no XOR pass (flags 0x40)
    ("PD2TITLE.GCP", 80, 400),   # title screen, two XOR passes (flags 0x60)
    ("USAGI.GCP", 10, 80),
]

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
    valid, custom, roundtrip, ramp = 0, [], 0, 0
    for f in gcp:
        blob = open(os.path.join(data_root, f), 'rb').read()
        pal = palette_from_packed(blob)
        if pal:
            valid += 1
            if palette_to_packed(pal) == blob[0x0B:0x0B + 32]:
                roundtrip += 1
            if tuple(tuple(c) for c in pal) == default:
                ramp += 1
            elif tuple(tuple(c) for c in pal) != default:
                custom.append(f)
    check(len(gcp) == EXPECT_GCP, f"{len(gcp)} .GCP files (expected {EXPECT_GCP})")
    check(valid == len(gcp), f"{valid}/{len(gcp)} have a valid packed palette at 0xB")
    check(len(custom) == EXPECT_GCP_CUSTOM,
          f"{len(custom)} carry a non-default palette: {custom}")

    # The packed channel order is pinned here, because getting it wrong swaps red
    # and green in every packed palette and only shows up as a colour cast:
    #   * 0xAA = green, 0xAC = red, 0xAE = blue (DOSBox-X vga_pc98_gdc.cpp),
    #     so byte[2i] = (index<<4)|G and byte[2i+1] = (R<<4)|B;
    #   * the game's own ramp must therefore come out as the PC-98 hardware ramp
    #     (entry i = G:i&4, R:i&2, B:i&1 -> 1 = blue, 2 = red, 4 = green).
    hardware = [(15 if i & 2 else 0, 15 if i & 4 else 0, 15 if i & 1 else 0)
                for i in range(16)]
    check(roundtrip == len(gcp),
          f"{roundtrip}/{len(gcp)} packed palettes re-encode byte-exactly "
          f"(the decode is the writer's inverse)")
    check([tuple(c) for c in DEFAULT_PALETTE][:8] == hardware[:8],
          "the default ramp decodes to the PC-98 hardware ramp "
          "(1 = blue, 2 = red, 3 = magenta, 4 = green)")
    check(ramp == valid - len(custom),
          f"{ramp} of {valid} .GCP carry that ramp")


def verify_exe_palettes(data_root):
    print("\n[6] screen palettes: 48-byte tables inside the EXEs (channel order B,R,G)")
    for name, off, want in EXPECT_EXE_PALETTES:
        p = os.path.join(data_root, name)
        if not os.path.isfile(p):
            check(False, f"{name} is missing")
            continue
        blob = open(p, 'rb').read()
        try:
            pal, order = palette_from_exe_table(blob, off)
        except ValueError as e:
            check(False, f"{name} @ {off:#x}: {e}")
            continue
        got = " ".join("%x%x%x" % t for t in pal)
        check(got == want and order == 'B,R,G',
              f"{name} @ {off:#x} -> {got if got != want else 'matches the live dump'} "
              f"(order {order})")
    try:
        import pal_tables
        rows = pal_tables.scan([data_root])
        check(len(rows) == EXPECT_TABLES_IN_DATA,
              f"{len(rows)} palette table(s) found in the data dir "
              f"(expected {EXPECT_TABLES_IN_DATA})")
    except ImportError:
        notes.append("tools/pal_tables.py not importable - table-count check skipped")


def verify_raw_block(data_root):
    print("\n[7] raw block: S_ROLL.ASK decodes as `u32 size` + LZSS from offset 4")
    p = os.path.join(data_root, 'S_ROLL.ASK')
    if not os.path.isfile(p):
        notes.append("S_ROLL.ASK not present - raw-block check skipped")
        return
    blob = open(p, 'rb').read()
    out = is_raw_block(blob)
    geom = raw_geometry(len(out)) if out else None
    check(out is not None, f"S_ROLL.ASK is a raw block ({len(out) if out else 0} bytes)")
    check(geom == (640, 320), f"its geometry derives as {geom}")


def verify_display_lists(data_root):
    print("\n[8] display lists: .GCP / CHARA.PCK run to their closing 0x7F")
    problems = []
    gcp = [f for f in sorted(os.listdir(data_root)) if f.upper().endswith('.GCP')]
    dl_gcp = 0
    for f in gcp:
        blob = open(os.path.join(data_root, f), 'rb').read()
        if not is_display_list(blob):
            continue
        dl_gcp += 1
        try:
            res = decode_displaylist(blob)
        except DisplayListError as e:
            problems.append(f"{f}: {e}")
            continue
        if res['consumed'] != res['stream']:
            problems.append(f"{f}: consumed {res['consumed']}/{res['stream']} bytes")
    check(dl_gcp == len(gcp) and bool(gcp),
          f"{dl_gcp}/{len(gcp)} .GCP files in the data dir are display lists")

    p = os.path.join(data_root, 'CHARA.PCK')
    dl_pck = 0
    if os.path.isfile(p):
        for i, blob in parse_archive(p):
            if not is_display_list(blob):
                continue
            dl_pck += 1
            try:
                res = decode_displaylist(blob)
            except DisplayListError as e:
                problems.append(f"CHARA.PCK#{i}: {e}")
                continue
            if res['consumed'] != res['stream']:
                problems.append(f"CHARA.PCK#{i}: consumed "
                                f"{res['consumed']}/{res['stream']} bytes")
        check(dl_pck == EXPECT_DISPLAYLIST_PCK,
              f"{dl_pck} display lists in CHARA.PCK (expected {EXPECT_DISPLAYLIST_PCK})")
    else:
        notes.append("CHARA.PCK not present - its display-list count is unchecked")
    check(not problems,
          "every display list consumed its stream exactly"
          if not problems else f"{len(problems)} problem(s): {problems[:5]}")

    print("\n[9] display-list geometry: width/height come from the block header")
    for fn, w, h in EXPECT_DISPLAYLIST_GEOMETRY:
        p = os.path.join(data_root, fn)
        if not os.path.isfile(p):
            notes.append(f"{fn} not present - geometry check skipped")
            continue
        try:
            got = parse_header(open(p, 'rb').read())
        except DisplayListError as e:
            check(False, f"{fn}: {e}")
            continue
        check((got['width'], got['height']) == (w, h),
              f"{fn}: {got['height']} rows x {got['width']} bytes "
              f"(expected {h} x {w})")


def verify_pd1(root, pd2_root):
    """Power Dolls 1: display lists, and the 48-byte tables in the other order."""
    print("\n[10] Power Dolls 1: display lists and the 48-byte table order")
    gcp = [f for f in sorted(os.listdir(root)) if f.upper().endswith('.GCP')]
    if not gcp:
        notes.append(f"{root}: no .GCP files - PD1 checks skipped")
        return
    problems = 0
    for f in gcp:
        blob = open(os.path.join(root, f), 'rb').read()
        if not is_display_list(blob):
            problems += 1
            continue
        try:
            res = decode_displaylist(blob)
        except DisplayListError as e:
            problems += 1
            print(f"        {f}: {e}")
            continue
        if res['consumed'] != res['stream']:
            problems += 1
    check(problems == 0, f"{len(gcp)} PD1 .GCP files decode as display lists, "
                         f"streams consumed")

    # The two games store the same screen palettes in different byte orders, and
    # the captured frames of the running game decide which: PD1's tables match
    # only when read as G,R,B (11/11 frames that match any table at all), PD2's
    # only as B,R,G.  The invariant that pins PD1 without a capture is that its
    # copy of the startup palette equals PD2's under the respective orders.
    pre = os.path.join(root, 'PREMIUM.EXE')
    sta = os.path.join(pd2_root, 'STARTUP.EXE')
    if not (os.path.isfile(pre) and os.path.isfile(sta)):
        notes.append("PREMIUM.EXE or STARTUP.EXE missing - the PD1 channel-order "
                     "cross-check was skipped")
        return
    pd2_blob = open(sta, 'rb').read()
    want, label = palette_from_exe_table(pd2_blob, 0x9311)
    blob = open(pre, 'rb').read()
    hits = []
    try:
        import pal_tables
        windows = [off for off, _tri in pal_tables.tables_in(blob, (0, 1, 2),
                                                             strict=False)]
    except ImportError:
        windows = range(0, len(blob) - 48)
    for off in windows:
        try:
            got, _ = palette_from_exe_table(blob, off, order='G,R,B')
        except ValueError:
            continue
        if got == want:
            hits.append(off)
    check(bool(hits),
          f"PREMIUM.EXE carries the PD2 startup palette ({label}) at "
          f"{[hex(h) for h in hits][:3]} when read as G,R,B"
          if hits else "PREMIUM.EXE does not hold the PD2 startup palette in "
                       "the G,R,B order")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=os.path.join('..', 'hdi', 'PD2D'),
                    help='directory with the game data files (PD2D)')
    ap.add_argument('--floppy', default=None,
                    help='root of the floppy releases, to also check those binaries')
    ap.add_argument('--pd1', default=None,
                    help='unpacked Power Dolls 1 data dir, for the PD1 checks')
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
    verify_exe_palettes(data_root)
    verify_raw_block(data_root)
    verify_display_lists(data_root)
    if a.pd1:
        pd1_root = os.path.abspath(a.pd1)
        if os.path.isdir(pd1_root):
            verify_pd1(pd1_root, data_root)
        else:
            notes.append(f"PD1 directory not found: {pd1_root}")

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
