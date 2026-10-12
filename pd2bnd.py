"""Power Dolls 2 / Advanced PD2 — the `.IDX` + `.BND` container pair.

Advanced PD2 does not ship the game's data files loose: it ships one bundle,
`PD2DT.BND`, next to a table of contents, `PD2DT.IDX`.  The pair is enough to
recover every payload file.

`.IDX` (the member table)
-------------------------
A flat array of 24-byte records, no header:

    +0..15   member name, NUL padded (ASCII, no path)
    +16..19  member size, u32 little endian
    +20..23  member offset inside the `.BND`, u32 little endian

The records are in payload order and the members are **concatenated without any
padding**: `offset[k] + size[k] == offset[k+1]` for every k, and the last member
ends exactly on the bundle's last byte.  That makes the table self-checking - a
wrong stride, a wrong endianness or a wrong field order shows up immediately as
a gap, an overlap or a run past the end.

`.BND` (the payload)
--------------------
The raw concatenation the table describes.  Nothing else: there is no header, no
compression and no alignment.  (Earlier work looked for the member table inside
the bundle and found the `BIGFILE`/`PD2DT.BND` strings of the *installer* data
that happens to be a member - `SAVEDATA.ORG`, `MAKEFILE`, `PD2DT.IDX`'s own
siblings - which is why the format resisted.)

Usage
-----
    python pd2bnd.py --list hdi/PD2_3/PD2DT.IDX
    python pd2bnd.py --idx hdi/PD2_3/PD2DT.IDX --bnd hdi/PD2_3/PD2DT.BND -o out/apd2
    python pd2bnd.py --auto out/apd2_hdi                     # every .IDX/.BND pair
    python pd2bnd.py --self-test

`--auto` carves each pair into `OUTDIR/<bundle stem>/` and leaves unrelated
files alone, so it is safe to run over a whole extracted installation.
"""
import argparse
import os
import struct
import sys
from pathlib import Path

__all__ = ["RECORD", "parse_idx", "split", "find_bundles"]

RECORD = 24
NAME_LEN = 16


class BundleError(Exception):
    pass


def _name(raw):
    return raw.split(b"\0")[0].decode("latin1")


def parse_idx(data):
    """-> [(name, size, offset)]  Raises BundleError when the table cannot be one."""
    if not data:
        raise BundleError("empty .IDX")
    if len(data) % RECORD:
        raise BundleError(f"{len(data)} bytes is not a multiple of {RECORD}")
    out = []
    cursor = 0
    for o in range(0, len(data), RECORD):
        name = _name(data[o:o + NAME_LEN])
        size, off = struct.unpack_from("<II", data, o + NAME_LEN)
        if not name or any(ord(c) < 32 or ord(c) > 126 for c in name):
            raise BundleError(f"record {o // RECORD}: implausible name {name!r}")
        out.append((name, size, off))
    # the monotonic contiguous layout is the decisive structural test
    cursor = 0
    for i, (name, size, off) in enumerate(out):
        if off != cursor:
            raise BundleError(f"record {i} ({name}): offset {off:,} != {cursor:,}")
        cursor = off + size
    return out


def split(idx_data, bnd_data, outdir=None, verbose=True):
    """Carve the bundle.  -> (members, report); writes files when outdir is given."""
    members = parse_idx(idx_data)
    end = members[-1][2] + members[-1][1]
    report = {
        "members": len(members),
        "bundle": len(bnd_data),
        "last_end": end,
        "exact": end == len(bnd_data),
        "trailing": len(bnd_data) - end,
    }
    if end > len(bnd_data):
        raise BundleError(f"the table asks for {end:,} bytes but the bundle has "
                          f"{len(bnd_data):,}")
    if outdir is not None:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        for name, size, off in members:
            (outdir / name).write_bytes(bnd_data[off:off + size])
    if verbose:
        print(f"{report['members']} member(s), last one ends at "
              f"{report['last_end']:,} of {report['bundle']:,} bytes"
              + ("" if report["exact"] else f"  ({report['trailing']:,} trailing)"))
    return members, report


def find_bundles(root):
    """Every `.IDX` that has a same-stem `.BND` next to it, under `root`."""
    found = []
    for dirpath, _dirs, files in os.walk(root):
        upper = {f.upper(): f for f in files}
        for fn in sorted(files):
            if not fn.upper().endswith(".IDX"):
                continue
            stem = fn[:-4]
            bnd = upper.get((stem + ".BND").upper())
            if bnd:
                found.append((Path(dirpath) / fn, Path(dirpath) / bnd))
    return found


def _self_test():
    """A synthetic pair plus the failure modes the format check must catch."""
    a, b, c = b"AAA.PCK", b"B.GCP", b"CCCCCCC.DAT"
    payload = b"".join([b"A" * 10, b"B" * 3, b"C" * 7])
    idx = b""
    off = 0
    for name, size, fill in ((a, 10, b"A"), (b, 3, b"B"), (c, 7, b"C")):
        idx += name + b"\0" * (NAME_LEN - len(name)) + struct.pack("<II", size, off)
        off += size
    members, report = split(idx, payload, verbose=False)
    assert [m[0] for m in members] == ["AAA.PCK", "B.GCP", "CCCCCCC.DAT"]
    assert report["exact"] and report["members"] == 3
    for bad, why in ((idx[:20], "truncated table"),
                     (idx[:RECORD] + b"\0" * RECORD, "bad name"),
                     (idx[:RECORD + 16:RECORD + 20] + struct.pack("<I", 99) + idx[RECORD + 20:],
                      "non-contiguous offset")):
        try:
            parse_idx(bad)
        except BundleError:
            pass
        else:
            raise AssertionError(f"accepted a {why}")
    try:
        split(idx, payload[:-1], verbose=False)
    except BundleError:
        pass
    else:
        raise AssertionError("accepted a bundle shorter than the table")
    print("self-test: OK")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--idx", metavar="FILE.IDX")
    src.add_argument("--auto", metavar="DIR", help="every .IDX/.BND pair under DIR")
    src.add_argument("--self-test", action="store_true")
    ap.add_argument("--bnd", metavar="FILE.BND", help="with --idx (default: same stem)")
    ap.add_argument("-o", "--out", metavar="DIR")
    ap.add_argument("--list", action="store_true", help="print the member table only")
    a = ap.parse_args()

    if a.self_test:
        _self_test()
        return
    if not a.idx and not a.auto:
        ap.error("one of --idx / --auto / --self-test is required")

    if a.idx:
        idx_path = Path(a.idx)
        bnd_path = Path(a.bnd) if a.bnd else idx_path.with_suffix(".BND")
        if not bnd_path.is_file():
            sys.exit(f"bundle not found: {bnd_path} (pass --bnd)")
        pairs = [(idx_path, bnd_path)]
    else:
        pairs = find_bundles(a.auto)
        if not pairs:
            sys.exit(f"{a.auto}: no .IDX with a matching .BND")

    for idx_path, bnd_path in pairs:
        print(f"== {idx_path.name} + {bnd_path.name}")
        members = parse_idx(idx_path.read_bytes())
        if a.list:
            cursor = 0
            for i, (name, size, off) in enumerate(members):
                print(f"  {i:3d}  {name:<16} {size:>10,} @ {off:>10,}"
                      + ("  <-- gap" if off != cursor else ""))
                cursor = off + size
            print(f"  {len(members)} member(s), {cursor:,} bytes")
            continue
        outdir = Path(a.out) if a.out else None
        if a.auto:
            outdir = (outdir or Path(".")) / bnd_path.stem
        if outdir is None:
            ap.error("-o/--out is required to carve")
        _, report = split(idx_path.read_bytes(), bnd_path.read_bytes(), outdir)
        print(f"  -> {outdir}  ({report['members']} file(s))")


if __name__ == "__main__":
    main()
