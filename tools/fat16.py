"""Read/write files inside an Anex86 HDI image (FAT12/16), from the host.

Why this exists
---------------
To run a palette dumper *inside* the guest you have to get a .COM file onto the
boot image and arrange for it to run. The Anex86 HDI header is 4096 bytes and
the filesystem behind it is plain FAT12/FAT16 with fixed-size (8.3) directory
entries - no LFN, no subdirectory trickery needed - so it can be edited safely
from Python with the game closed.

Safety model: nothing is written until you call `save()`/`--apply`, and writes
go to the image you name. Always work on a copy (`--copy-to`) and keep a
backup; DOSBox-X must not be running on that image.

Usage
-----
    python tools\\fat16.py IMAGE.HDI --list
    python tools\\fat16.py IMAGE.HDI --put tools\\PALDUMP.COM PD2PAL.COM
    python tools\\fat16.py IMAGE.HDI --get AUTOEXEC.BAT -o out\\autoexec.bat
    python tools\\fat16.py IMAGE.HDI --backup AUTOEXEC.BAT -o out --apply
    python tools\\fat16.py IMAGE.HDI --put-bytes AUTOEXEC.BAT out\\autoexec.bat --apply
    python tools\\fat16.py IMAGE.HDI --rm PD2PAL.COM --apply
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

HDI_HEADER = 4096
ATTR_VOLUME = 0x08
ATTR_DIR = 0x10


def dos_name(name: str) -> str:
    """'PD2PAL.COM' -> the 11-byte padded form used in directory entries."""
    name = name.upper()
    stem, _, ext = name.partition(".")
    return (stem[:8].ljust(8) + ext[:3].ljust(3)).encode("ascii")


class FatImage:
    def __init__(self, path: Path, data: bytes | None = None):
        self.path = Path(path)
        self.data = bytearray(data if data is not None else self.path.read_bytes())
        self._parse()

    # ---------------------------------------------------------------- parsing
    def _parse(self) -> None:
        bs = HDI_HEADER
        if self.data[bs + 510:bs + 512] != b"\x55\xaa":
            # maybe the image has no Anex86 header
            if self.data[510:512] == b"\x55\xaa":
                bs = 0
            else:
                raise SystemExit("no FAT boot sector at 4096 or 0 (not an Anex86 HDI?)")
        d = self.data
        self.bs = bs
        self.bps = struct.unpack_from("<H", d, bs + 11)[0]
        self.spc = d[bs + 13]
        self.reserved = struct.unpack_from("<H", d, bs + 14)[0]
        self.nfats = d[bs + 16]
        self.root_entries = struct.unpack_from("<H", d, bs + 17)[0]
        self.spf = struct.unpack_from("<H", d, bs + 22)[0]
        self.total_sectors = struct.unpack_from("<H", d, bs + 19)[0] or \
            struct.unpack_from("<I", d, bs + 32)[0]
        self.media = d[bs + 21]
        self.root_start = bs + (self.reserved + self.nfats * self.spf) * self.bps
        self.root_sectors = (self.root_entries * 32 + self.bps - 1) // self.bps
        self.data_start = self.root_start + self.root_sectors * self.bps
        total_clusters = (self.total_sectors - (self.reserved + self.nfats * self.spf
                                                + self.root_sectors)) // self.spc
        self.fat16 = total_clusters >= 4085
        self.fat_start = bs + self.reserved * self.bps
        if self.media != 0xF8 and self.media != 0xF0:
            pass                                    # keep going, not fatal
        self.cluster_count = total_clusters

    @property
    def cluster_bytes(self) -> int:
        return self.bps * self.spc

    def info(self) -> str:
        return (f"{self.path.name}: FAT{'16' if self.fat16 else '12'}, "
                f"bps={self.bps} spc={self.spc} reserved={self.reserved} "
                f"fats={self.nfats} spf={self.spf} root_entries={self.root_entries} "
                f"clusters={self.cluster_count} "
                f"({self.cluster_count * self.cluster_bytes} data bytes), "
                f"data starts at 0x{self.data_start:X}")

    # ------------------------------------------------------------- FAT access
    def fat_get(self, cluster: int) -> int:
        if self.fat16:
            return struct.unpack_from("<H", self.data, self.fat_start + cluster * 2)[0]
        # FAT12
        off = self.fat_start + (cluster * 3) // 2
        val = struct.unpack_from("<H", self.data, off)[0]
        return (val >> 4) if cluster & 1 else (val & 0x0FFF)

    def fat_set(self, cluster: int, value: int) -> None:
        for n in range(self.nfats):
            base = self.fat_start + n * self.spf * self.bps
            if self.fat16:
                struct.pack_into("<H", self.data, base + cluster * 2, value & 0xFFFF)
            else:
                off = base + (cluster * 3) // 2
                cur = struct.unpack_from("<H", self.data, off)[0]
                if cluster & 1:
                    cur = (cur & 0x000F) | ((value & 0x0FFF) << 4)
                else:
                    cur = (cur & 0xF000) | (value & 0x0FFF)
                struct.pack_into("<H", self.data, off, cur)

    def chain(self, start: int) -> list[int]:
        out, seen = [], set()
        c = start
        while 2 <= c < 0xFFF0 and c not in seen:
            out.append(c)
            seen.add(c)
            if len(out) > self.cluster_count + 8:
                raise SystemExit("FAT chain loop")
            c = self.fat_get(c)
        return out

    def alloc(self, count: int) -> list[int]:
        free = [c for c in range(2, self.cluster_count + 2) if self.fat_get(c) == 0]
        if len(free) < count:
            raise SystemExit(f"not enough free clusters: need {count}, have {len(free)}")
        return free[:count]

    def free_chain(self, start: int) -> None:
        for c in self.chain(start):
            self.fat_set(c, 0)

    # --------------------------------------------------------- cluster access
    def cluster_off(self, cluster: int) -> int:
        return self.data_start + (cluster - 2) * self.cluster_bytes

    def read_chain(self, start: int, size: int | None = None) -> bytes:
        out = bytearray()
        for c in self.chain(start):
            out += self.data[self.cluster_off(c):self.cluster_off(c) + self.cluster_bytes]
        return bytes(out if size is None else out[:size])

    def write_chain(self, clusters: list[int], payload: bytes) -> None:
        cb = self.cluster_bytes
        for i, c in enumerate(clusters):
            chunk = payload[i * cb:(i + 1) * cb]
            chunk = chunk + b"\x00" * (cb - len(chunk))
            off = self.cluster_off(c)
            self.data[off:off + cb] = chunk
        for i, c in enumerate(clusters):
            nxt = clusters[i + 1] if i + 1 < len(clusters) else 0xFFFF
            self.fat_set(c, nxt)

    # --------------------------------------------------------- directory ops
    def _root_entries(self):
        for i in range(self.root_entries):
            off = self.root_start + i * 32
            e = self.data[off:off + 32]
            if e[0] == 0x00:
                return
            yield i, off, e

    def listdir(self):
        rows = []
        for i, off, e in self._root_entries():
            if e[0] == 0xE5 or e[11] & ATTR_VOLUME:
                continue
            name = e[:8].decode("ascii", "replace").strip()
            ext = e[8:11].decode("ascii", "replace").strip()
            size = struct.unpack_from("<I", e, 28)[0]
            start = struct.unpack_from("<H", e, 26)[0]
            rows.append((f"{name}.{ext}" if ext else name, e[11], size, start, off))
        return rows

    def find(self, name: str):
        want = dos_name(name)
        for i, off, e in self._root_entries():
            if e[0] == 0xE5:
                continue
            if bytes(e[:11]) == want:
                return off, e
        return None

    def read_file(self, name: str) -> bytes:
        hit = self.find(name)
        if not hit:
            raise SystemExit(f"{name}: not found in root directory")
        off, e = hit
        size = struct.unpack_from("<I", e, 28)[0]
        start = struct.unpack_from("<H", e, 26)[0]
        return self.read_chain(start, size)

    def write_file(self, name: str, payload: bytes, mtime: int = 0) -> None:
        want = dos_name(name)
        cb = self.cluster_bytes
        need = max(1, (len(payload) + cb - 1) // cb)
        clusters = self.alloc(need)
        self.write_chain(clusters, payload)

        hit = self.find(name)
        if hit:
            off, e = hit
            old_start = struct.unpack_from("<H", e, 26)[0]
            if old_start:
                self.free_chain(old_start)
        else:
            off = None
            for i in range(self.root_entries):
                o = self.root_start + i * 32
                if self.data[o] in (0x00, 0xE5):
                    off = o
                    break
            if off is None:
                raise SystemExit("root directory is full")
        entry = bytearray(32)
        entry[0:11] = want
        entry[11] = 0x20
        struct.pack_into("<H", entry, 26, clusters[0])
        struct.pack_into("<I", entry, 28, len(payload))
        self.data[off:off + 32] = entry

    def delete_file(self, name: str) -> None:
        hit = self.find(name)
        if not hit:
            raise SystemExit(f"{name}: not found")
        off, e = hit
        start = struct.unpack_from("<H", e, 26)[0]
        if start:
            self.free_chain(start)
        self.data[off] = 0xE5

    # ------------------------------------------------------------------ io
    def save(self, path: Path | None = None) -> None:
        dst = Path(path) if path else self.path
        dst.write_bytes(self.data)
        print(f"wrote {dst} ({len(self.data)} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--get", metavar="NAME")
    ap.add_argument("--put", nargs=2, metavar=("HOSTFILE", "DOSNAME"))
    ap.add_argument("--put-bytes", nargs=2, metavar=("DOSNAME", "HOSTFILE"))
    ap.add_argument("--rm", metavar="NAME")
    ap.add_argument("--backup", metavar="NAME", help="copy this file out first")
    ap.add_argument("-o", "--out", type=Path, help="output dir/file for --get/--backup")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the image (otherwise this is a dry run)")
    a = ap.parse_args()

    img = FatImage(Path(a.image))
    print(img.info())

    if a.list or not any([a.get, a.put, a.put_bytes, a.rm, a.backup]):
        print(f"{'name':<14} {'attr':<5} {'size':>8}  start")
        for name, attr, size, start, _ in img.listdir():
            flag = "DIR" if attr & ATTR_DIR else "   "
            print(f"{name:<14} {attr:02X} {flag} {size:>8}  {start}")
        return 0

    if a.backup:
        data = img.read_file(a.backup)
        dst = (a.out / a.backup) if (a.out and a.out.is_dir()) or a.out is None else a.out
        if dst is None:
            dst = Path(a.backup + ".bak")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        print(f"backed up {a.backup} -> {dst} ({len(data)} bytes)")

    if a.get:
        data = img.read_file(a.get)
        dst = a.out if (a.out and not a.out.is_dir()) else (a.out or Path(".")) / a.get
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        print(f"extracted {a.get} -> {dst} ({len(data)} bytes)")

    if a.put:
        host, dos = a.put
        payload = Path(host).read_bytes()
        img.write_file(dos, payload)
        print(f"put {host} -> {dos} ({len(payload)} bytes)")

    if a.put_bytes:
        dos, host = a.put_bytes
        payload = Path(host).read_bytes()
        img.write_file(dos, payload)
        print(f"put {host} -> {dos} ({len(payload)} bytes)")

    if a.rm:
        img.delete_file(a.rm)
        print(f"deleted {a.rm}")

    if a.apply:
        img.save()
    else:
        print("dry run: pass --apply to write the image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
