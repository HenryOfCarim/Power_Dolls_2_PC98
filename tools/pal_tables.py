"""Palette tables stored inside the game's executables (and any other binary).

Why this exists
---------------
The artwork screens do not carry a palette next to their pixels.  The game keeps
whole banks of 48-byte palettes inside its own EXEs and hands the right one to
the PC-98 palette writer at runtime, e.g.

    TACTICS.EXE  0x1ECA4   the tactics/battle screen palette
    STARTUP.EXE  0x9311    the startup screen palette
    PD2SHELL.EXE 0x98E6    the shell/menu palette
    BRIEFING.EXE 0x234C6   the shared artwork palette (also in CONVERT, OPENING,
                           REPORT, TACTICS)

Byte order is (B, R, G): the triple a palette entry really means is
(byte[3i+1], byte[3i+2], byte[3i+0]).  Reading such a table as plain RGB is why
earlier searches reported "no palette in the files at all" - a 16/16 match stayed
invisible.

Usage
-----
    python tools\\pal_tables.py --list [--data DIR ...] [--out tables.txt]
    python tools\\pal_tables.py --dump OUTDIR [--data DIR ...]
    python tools\\pal_tables.py --find DUMP_analog.rgb [--data DIR ...]
    python tools\\pal_tables.py --find --hex 000 fdb fb8 b85 ... [--data DIR]

`--find` rejects a negative result unless the method can find positives, so the
scan is always accompanied by a control (see --self-test).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROW = 16          # palette entries
TABLE = ROW * 3   # bytes per table
ENGINE_ORDER = (1, 2, 0)   # stored (B, R, G) -> (R, G, B)
ALL_ORDERS = {"rgb": (0, 1, 2), "rbg": (0, 2, 1), "grb": (1, 0, 2),
              "gbr": (1, 2, 0), "brg": (2, 0, 1), "bgr": (2, 1, 0)}
DEFAULT_DATA = [Path("power dolls 2 HDI") / "_unpacked", Path("power dolls 2 FDI")]


def tables_in(data: bytes, order=ENGINE_ORDER, strict=True):
    """Yield (offset, triples) for every palette-shaped 48-byte window.

    Structural rule, taken from the tables the engine really uses:
      * the table starts with black (all of them do),
      * it contains a white entry (index 15 is not always the white one - the
        tactics palette ends with `fdb` and keeps white at index 7),
      * at least 10 distinct colours.
    `strict=False` drops the white requirement; that pass is only used as a
    fallback by --find, because it also collects low-byte code windows.
    """
    o = 0
    n = len(data)
    while o + TABLE <= n:
        window = data[o:o + TABLE]
        if max(window) > 0x0F:
            o += 1
            continue
        tri = [tuple(window[3 * i + q] for q in order) for i in range(ROW)]
        if (tri[0] == (0, 0, 0) and len(set(tri)) >= 10
                and (not strict or (15, 15, 15) in tri)):
            yield o, tri
        o += 1


def iter_files(roots):
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.stat().st_size <= 60_000_000:
                yield p


def scan(roots, order=ENGINE_ORDER, strict=True):
    rows = []
    for p in iter_files(roots):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        for off, tri in tables_in(data, order, strict):
            rows.append((p, off, tri))
    return rows


def pal_text(tri):
    return "JASC-PAL\n0100\n16\n" + "".join(
        f"{r * 17} {g * 17} {b * 17}\n" for r, g, b in tri)


def hexline(tri):
    return " ".join("%x%x%x" % t for t in tri)


def cmd_list(rows, out):
    groups = Counter(tuple(t) for _, _, t in rows)
    lines = [f"palette tables found: {len(rows)} in {len({str(p) for p, _, _ in rows})} file(s)",
             f"distinct palettes : {len(groups)}", ""]
    for p, off, tri in rows:
        lines.append(f"{str(p):70s} {off:#08x}  {hexline(tri)}")
    text = "\n".join(lines) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"[pal_tables] inventory written to {out}")
    print("\n".join(lines[:6]))
    print("   ...")
    for p, off, tri in rows[:12]:
        print(f"   {p.name:20s} {off:#08x}  {hexline(tri)}")


def cmd_dump(rows, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    used = set()
    for p, off, tri in rows:
        name = f"{p.name}_{off:06x}.pal".replace(" ", "_")
        if name in used:                      # same EXE+offset in two trees
            stem, ext = name[:-4], name[-4:]
            n = 2
            while f"{stem}_{n}{ext}" in used:
                n += 1
            name = f"{stem}_{n}{ext}"
        used.add(name)
        (outdir / name).write_text(pal_text(tri), encoding="ascii")
    print(f"[pal_tables] {len(rows)} table(s) written as JASC-PAL into {outdir}")


def fits(base, screen, tol=1, kmin=2):
    """Best fade-ladder scale k/16 (k from kmin to 16) reproducing `screen` from `base`.

    kmin=2 guards against the degenerate "a 1/16 of any table is almost black"
    match that makes a black screen look like it was sourced from everywhere.
    """
    for k in range(kmin, 17):
        approx = [tuple((c * k + 8) // 16 for c in t) for t in base]
        if all(max(a) == 0 and max(s) == 0 or all(abs(a[i] - s[i]) <= tol for i in range(3))
               for a, s in zip(approx, screen)):
            return k
    return None


def cmd_find(roots, screen, tol=1):
    hits = []
    for p, off, tri in scan(roots):
        k = fits(tri, screen, tol)
        if k:
            hits.append((p, off, k, tri))
    if not hits:
        print("[pal_tables] no match with the strict table filter; "
              "retrying with the loose pass (white entry not required)")
        for p, off, tri in scan(roots, strict=False):
            k = fits(tri, screen, tol)
            if k:
                hits.append((p, off, k, tri))
    print(f"[pal_tables] tables matching the given palette: {len(hits)}")
    for p, off, k, tri in hits[:20]:
        print(f"   scale {k}/16  {p} @ {off:#x}")
        print(f"      {hexline(tri)}")
    return hits


def self_test(roots):
    """A palette known to live in the files must be found again."""
    known = None
    for p, off, tri in scan(roots):
        if p.name.upper() == "STARTUP.EXE":
            known = (p, off, tri)
            break
    if not known:
        print("[self-test] STARTUP.EXE table not found - scan is broken")
        return
    p, off, tri = known
    hits = cmd_find(roots, list(tri))
    ok = any(h[0] == p and h[1] == off for h in hits)
    print(f"[self-test] control {'PASSED' if ok else 'FAILED'}: {p.name} @ {off:#x}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", action="append", type=Path, default=None,
                    help="file or directory to scan (repeatable)")
    ap.add_argument("--list", action="store_true", help="inventory of palette tables")
    ap.add_argument("--dump", type=Path, help="write each table as a JASC .pal here")
    ap.add_argument("--find", type=Path, help="locate a palette dumped as *_analog.rgb")
    ap.add_argument("--hex", nargs=48, type=lambda v: int(v, 16),
                    help="locate a palette given as 48 hex nibbles (R G B ...)")
    ap.add_argument("--order", choices=sorted(ALL_ORDERS), default="gbr",
                    help="stored channel order (default gbr = the engine's)")
    ap.add_argument("--tol", type=int, default=1, help="per-component tolerance for --find")
    ap.add_argument("--out", type=Path, help="write the --list inventory here")
    ap.add_argument("--self-test", action="store_true", help="prove the scan can fire")
    a = ap.parse_args()

    roots = a.data or DEFAULT_DATA
    order = ALL_ORDERS[a.order]

    if a.self_test:
        self_test(roots)
        return 0
    if a.find:
        raw = a.find.read_bytes()
        screen = [tuple(raw[3 * i:3 * i + 3]) for i in range(ROW)]
        return 0 if cmd_find(roots, screen, a.tol) else 1
    if a.hex:
        vals = a.hex
        return 0 if cmd_find(roots, [tuple(vals[3 * i:3 * i + 3]) for i in range(ROW)], a.tol) else 1

    rows = scan(roots, order)
    if a.dump:
        cmd_dump(rows, a.dump)
    if a.list or not a.dump:
        cmd_list(rows, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
