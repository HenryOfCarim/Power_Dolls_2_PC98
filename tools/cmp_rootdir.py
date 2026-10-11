"""Compare the root directory of two PD2 HDI images, entry by entry.

Used to verify that the file injector changed exactly what it meant to change
and nothing else. Diagnostic only - it never writes.

    python tools\\cmp_rootdir.py PRistine.HDI modified.HDI
"""
from __future__ import annotations

import argparse
import sys
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hdi98 import open_fs      # noqa: E402


def entries(fs, count=40):
    raw = fs._read_fs_bytes(fs.first_root_sector * fs.bytes_per_sector, count * 32)
    out = []
    for i in range(count):
        e = raw[i * 32:(i + 1) * 32]
        out.append(bytes(e))
    return out


def describe(e: bytes) -> str:
    if not any(e):
        return "<empty>"
    if e[0] == 0xE5:
        return "<deleted>"
    name = e[:11]
    cluster, size = struct.unpack_from("<HI", e, 26)
    return f"{name!r} attr={e[11]:02X} cluster={cluster} size={size}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--count", type=int, default=40)
    a = ap.parse_args()

    _, fa = open_fs(a.a)
    _, fb = open_fs(a.b)
    ea, eb = entries(fa, a.count), entries(fb, a.count)
    print(f"root dir: {fa.first_root_sector}@{fa.bytes_per_sector}B  "
          f"{fa.fs_type_label} vs {fb.fs_type_label}")
    diff = 0
    for i, (x, y) in enumerate(zip(ea, eb)):
        if x == y:
            continue
        diff += 1
        print(f"[{i:2d}] A {describe(x)}")
        print(f"     B {describe(y)}")
        if x[:11] != y[:11]:
            print("      ^ filename differs")
    if not diff:
        print("root directories are identical")
    else:
        print(f"{diff} differing entries")
    # FAT comparison summary
    fa_fat = fa._fat_data
    fb_fat = fb._fat_data
    if fa_fat != fb_fat:
        n = sum(1 for i in range(min(len(fa_fat), len(fb_fat))) if fa_fat[i] != fb_fat[i])
        print(f"FAT differs in {n} bytes")
    else:
        print("FAT identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
