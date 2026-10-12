"""Extract every file from a PC-98 disk image (HDI / FDI / FDD / raw).

98Bridge covers the usual cases, but several of the dumps shipped with this
project do not present a BPB where it expects one:

* `MS-DOS.FDI`            - plain FAT12 at offset 0, media byte 0xFE (98Bridge
                            rejects it),
* `*-S-Premium Disc.fdi`  - FAT12 behind a 0x1000-byte wrapper,
* `*.fdd` (VFD dumps)     - 1024 B/sector images whose boot sector is not at 0.

So this tool carries its own FAT12/FAT16 reader.  It locates the filesystem by
validating a BPB (geometry + FAT media byte + size that fits the image) at a
series of candidate bases, then walks the directory tree and writes every file
out with its original name.

    python tools\\img_extract.py --probe IMAGE [IMAGE ...]
    python tools\\img_extract.py IMAGE -o OUTDIR [--base 0x1000]
    python tools\\img_extract.py --all IMAGEDIR -o OUTDIR   # every .fdi/.fdd/.hdi
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

IMAGE_EXT = (".fdi", ".fdd", ".hdi", ".nhd", ".img", ".d88", ".hdm")
BASES = (0, 0x1000, 0x400, 0x2000, 0x800, 0x200, 0x100, 0x4000, 0x8000, 4)


class Layout:
    __slots__ = ("base", "bps", "spc", "res", "nf", "root", "tot", "media", "spf",
                 "fat_start", "root_start", "data_start", "clusters", "fat16")

    def __repr__(self):
        kind = "FAT16" if self.fat16 else "FAT12"
        return (f"base={self.base:#x} {kind} {self.bps}B/sector spc={self.spc} "
                f"res={self.res} fats={self.nf} root={self.root} sectors={self.tot} "
                f"spf={self.spf} media={self.media:#04x} clusters={self.clusters}"
                f" data@{self.data_start:#x}")


def parse_bpb(d: bytes, base: int) -> Layout | None:
    if base + 0x18 > len(d):
        return None
    bps, spc, res, nf, root, tot, media, spf = struct.unpack_from("<HBHBHHBH", d, base + 0x0B)
    if bps not in (512, 1024, 2048, 4096):
        return None
    if spc not in (1, 2, 4, 8, 16, 32, 64, 128):
        return None
    if not (1 <= res <= 32) or nf not in (1, 2) or not (16 <= root <= 512) or root % 16:
        return None
    if not (1 <= spf <= 64) or tot == 0:
        return None
    total_bytes = tot * bps
    if base + total_bytes > len(d) + bps:          # allow one short sector
        return None
    fat_start = base + res * bps
    root_start = fat_start + nf * spf * bps
    data_start = root_start + root * 32
    if data_start >= base + total_bytes:
        return None
    clusters = (base + total_bytes - data_start) // (spc * bps)
    if clusters < 100:
        return None
    if fat_start >= len(d):
        return None
    first_fat_byte = d[fat_start]
    if media and first_fat_byte != media:          # the FAT starts with the media byte
        return None
    lay = Layout()
    lay.base, lay.bps, lay.spc, lay.res, lay.nf = base, bps, spc, res, nf
    lay.root, lay.tot, lay.media, lay.spf = root, tot, media, spf
    lay.fat_start, lay.root_start, lay.data_start = fat_start, root_start, data_start
    lay.clusters = clusters
    lay.fat16 = clusters >= 4085
    return lay


def find_layout(d: bytes, bases=BASES, scan_limit=0x20000):
    """-> (Layout, how) or (None, reason)."""
    for base in bases:
        lay = parse_bpb(d, base)
        if lay:
            return lay, f"BPB at {base:#x}"
    lay, how = find_layout_nobpb(d)
    if lay:
        return lay, how
    # last resort: look for a BPB-like structure anywhere near the start
    for base in range(0, min(scan_limit, max(0, len(d) - 0x40)), 2):
        lay = parse_bpb(d, base)
        if lay:
            return lay, f"BPB found by scan at {base:#x}"
    return None, "no self-consistent BPB found"


# ------------------------------------------------------- FAT without a BPB
# Some PC-98 releases (Advanced Power Dolls 2's .fdd dumps) have no usable BPB at
# all: a custom boot sector, and the image even lacks its first 4 bytes.  The
# layout can still be recovered from the directory itself, because the files are
# stored contiguously: entry[k+1].cluster == entry[k].cluster + ceil(size/clus).
NOBPB_ATTRS = (0x00, 0x01, 0x02, 0x10, 0x20, 0x30)
NOBPB_CLUS = (512, 1024, 2048, 4096)


def _entries_at(d: bytes, root: int, clus_at=0x1A, size_at=0x1C, limit=512):
    out = []
    for k in range(limit):
        o = root + 32 * k
        e = d[o:o + 32]
        if len(e) < 32 or e[0] == 0x00:
            break
        if e[0] == 0xE5:
            continue
        attr = e[0x0B]
        if attr not in NOBPB_ATTRS or not all(32 <= c < 127 for c in e[0:11]):
            return None
        clus = int.from_bytes(e[clus_at:clus_at + 2], "little")
        size = int.from_bytes(e[size_at:size_at + 4], "little")
        if size >= 4_000_000 or clus >= 4096:
            return None
        out.append((e[0:8].decode("latin1").rstrip() + "." + e[8:11].decode("latin1").rstrip(),
                    attr, clus, size))
    return out or None


NOBPB_ENTRY_COUNTS = (16, 32, 64, 112, 128, 192, 224, 240, 256)


def find_layout_nobpb(d: bytes):
    """Recover (root, data, cluster size) from a contiguous-file directory.

    The directory fixes the *relative* layout (via the contiguity of the files);
    the absolute one is pinned by validation: the entry count that makes the most
    `.EXE` entries actually start with 'MZ' is the right one.
    """
    for root in range(0x200, min(len(d) - 32 * 8, 0x40000)):
        ents = _entries_at(d, root)
        if not ents:
            continue
        used = [e for e in ents if e[2] >= 2 and e[3] > 0]
        if not used:
            continue
        best = None
        for n_entries in NOBPB_ENTRY_COUNTS:
            if n_entries < len(ents):
                continue
            data_start = root + 32 * n_entries
            if data_start >= len(d):
                continue
            for clus_size in NOBPB_CLUS:
                ok = 0
                prev = None
                for _name, _attr, clus, size in used:
                    if prev is not None:
                        want = prev[0] + -(-prev[1] // clus_size)
                        if clus == want:
                            ok += 1
                    prev = (clus, size)
                if ok < max(0, len(used) - 2):
                    continue
                mz = 0
                fits = 0
                last_end = 0
                for name, _attr, clus, size in used:
                    off = data_start + (clus - 2) * clus_size
                    if off + size <= len(d):
                        fits += 1
                        last_end = max(last_end, off + size)
                    if name.upper().endswith((".EXE", ".COM")) and d[off:off + 2] == b"MZ":
                        mz += 1
                # a tiny directory (one big data volume) is only credible if the
                # single file actually fits
                if len(used) <= 2 and fits < len(used):
                    continue
                # the data area of a distribution disk is filled to the end, so the
                # best layout is the one whose files reach furthest into the image
                slack = (len(d) - last_end) if last_end else len(d)
                score = (mz, fits, -slack)
                if best is None or score > best[0]:
                    best = (score, n_entries, clus_size, data_start, ok, len(used))
        if best:
            score, n_entries, clus_size, data_start, ok, n_used = best
            lay = Layout()
            lay.base = 0
            lay.bps, lay.spc = clus_size, 1
            lay.res = lay.nf = 0
            lay.root = n_entries
            lay.tot = (len(d) - data_start) // clus_size
            lay.media, lay.spf = 0, 0
            lay.fat_start = None
            lay.root_start = root
            lay.data_start = data_start
            lay.clusters = lay.tot
            lay.fat16 = False
            return lay, (f"no BPB: directory at {root:#x}, {n_entries} entries, "
                         f"data at {data_start:#x}, cluster {clus_size} B, "
                         f"{ok}/{n_used - 1} contiguous pairs, {score[0]} MZ anchor(s)")
    return None, "no self-consistent BPB or directory found"


def fat_entry(d: bytes, lay: Layout, cluster: int) -> int:
    if lay.fat16:
        o = lay.fat_start + cluster * 2
        return struct.unpack_from("<H", d, o)[0] if o + 2 <= len(d) else 0xFFFF
    o = lay.fat_start + (cluster * 3) // 2
    if o + 2 > len(d):
        return 0xFFF
    v = struct.unpack_from("<H", d, o)[0]
    return (v >> 4) if cluster & 1 else (v & 0x0FFF)


def chain(d: bytes, lay: Layout, cluster: int, limit=None):
    """Cluster chain, stopping on a bad value or a loop."""
    if lay.fat16:
        eof = 0xFFF8
    else:
        eof = 0xFF8
    seen = set()
    limit = limit or lay.clusters + 2
    while 2 <= cluster < lay.clusters + 2 and cluster not in seen and len(seen) < limit:
        yield cluster
        seen.add(cluster)
        nxt = fat_entry(d, lay, cluster)
        if nxt >= eof or nxt == 0 or nxt == 1:
            return
        cluster = nxt


def cluster_bytes(d: bytes, lay: Layout, cluster: int) -> bytes:
    o = lay.data_start + (cluster - 2) * lay.spc * lay.bps
    return d[o:o + lay.spc * lay.bps]


def read_dir(d: bytes, lay: Layout, start: int, size: int):
    """Yield (name, attr, first_cluster, file_size) for a directory area."""
    for o in range(start, min(start + size, len(d)), 32):
        e = d[o:o + 32]
        if len(e) < 32 or e[0] == 0x00:
            return
        if e[0] == 0xE5:
            continue
        attr = e[0x0B]
        if attr == 0x0F:                            # long-file-name slot
            continue
        if attr & 0x08:                             # volume label
            continue
        raw = e[0:8].decode("latin1").rstrip(" ")
        ext = e[8:11].decode("latin1").rstrip(" ")
        name = f"{raw}.{ext}" if ext else raw
        cluster = struct.unpack_from("<H", e, 0x1A)[0]
        size = struct.unpack_from("<I", e, 0x1C)[0]
        yield name, attr, cluster, size


def iter_tree(d: bytes, lay: Layout):
    """Yield (path, first_cluster, size) for every file, depth-first."""
    stack = [("", lay.root_start, lay.root * 32)]
    while stack:
        prefix, start, size = stack.pop()
        for name, attr, cluster, fsize in read_dir(d, lay, start, size):
            if name in (".", ".."):
                continue
            path = f"{prefix}/{name}" if prefix else name
            if attr & 0x10:
                stack.append((path, lay.data_start + (cluster - 2) * lay.spc * lay.bps,
                              lay.clusters * lay.spc * lay.bps))
            else:
                yield path, cluster, fsize


def extract(image: Path, outdir: Path, base=None, verbose=True):
    d = image.read_bytes()
    if base is None:
        lay, how = find_layout(d)
    else:
        lay, how = parse_bpb(d, base), f"forced base {base:#x}"
        if lay is None:
            return None, f"forced base {base:#x} does not hold a valid BPB"
    if lay is None:
        return None, how
    outdir.mkdir(parents=True, exist_ok=True)
    n, bad = 0, 0

    if lay.fat_start is None:
        # no FAT available: rely on the contiguous-file property the layout
        # detector verified (entry[k+1].cluster == entry[k].cluster + ceil(size))
        ents = _entries_at(d, lay.root_start, limit=lay.root) or []
        for name, attr, clus, size in ents:
            if size == 0 or clus < 2:
                continue
            off = lay.data_start + (clus - 2) * lay.spc * lay.bps
            if off >= len(d):
                bad += 1
                continue
            blob = d[off:off + size]
            if len(blob) < size:
                bad += 1
            (outdir / name).write_bytes(blob)
            n += 1
            if verbose and n <= 8:
                print(f"    {size:>9}  {name}" + ("  [short]" if len(blob) < size else ""))
        return (lay, how, n, bad), None

    for path, cluster, size in iter_tree(d, lay):
        target = outdir / path.replace("\\", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray()
        for c in chain(d, lay, cluster):
            data += cluster_bytes(d, lay, c)
            if len(data) >= size:
                break
        if len(data) < size:
            bad += 1
        target.write_bytes(bytes(data[:size]))
        n += 1
        if verbose and n <= 8:
            print(f"    {size:>9}  {path}")
    return (lay, how, n, bad), None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="*", type=Path, help="disk image(s) to extract")
    ap.add_argument("-o", "--outdir", type=Path)
    ap.add_argument("--all", type=Path, help="extract every image found under this directory")
    ap.add_argument("--probe", action="store_true", help="only report the filesystem layout")
    ap.add_argument("--base", type=lambda v: int(v, 0), default=None,
                    help="force the filesystem base offset (e.g. 0x1000)")
    a = ap.parse_args()

    images = []
    if a.all:
        for p in sorted(a.all.rglob("*")):
            if p.is_file() and p.suffix.lower() in IMAGE_EXT:
                images.append(p)
    elif a.image:
        images = list(a.image)
    else:
        ap.error("give an IMAGE (with -o OUTDIR), --all DIR, or --probe IMAGE ...")

    if a.probe:
        for p in images:
            d = p.read_bytes()
            if a.base is None:
                lay, how = find_layout(d)
            else:
                lay, how = parse_bpb(d, a.base), f"forced base {a.base:#x}"
            print(f"{p.name}  ({len(d)} bytes)")
            print(f"    {lay if lay else '-> ' + how}")
        return 0

    if not a.outdir:
        ap.error("OUTDIR is required for extraction (-o OUTDIR)")
    fails = 0
    multi = len(images) > 1 or bool(a.all)
    for p in images:
        dest = a.outdir / p.stem if multi else a.outdir
        res, err = extract(p, dest, a.base)
        if err:
            print(f"  FAIL {p.name}: {err}")
            fails += 1
        else:
            lay, how, n, bad = res
            print(f"  OK   {p.name}: {n} file(s) -> {dest}"
                  + (f"  [{bad} short/truncated]" if bad else "")
                  + f"   ({how}; {lay})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
