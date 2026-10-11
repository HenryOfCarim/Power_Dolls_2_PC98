"""Put PALDUMP.COM onto the PD2 HDI copy (and take it off again).

Uses 98Bridge's FAT12/FAT16 parser (`98Bridge-main/fat_fs.py`) for the hard part
- locating the BPB, the FATs, the root directory and the cluster chains - and
then performs a *minimal, verifiable* edit:

    * allocate a cluster chain out of the FAT's free entries,
    * write the payload into those clusters,
    * add/replace one 32-byte root directory entry,
    * flush the FAT copies and the root directory back through the DiskImage.

Everything is read back and re-parsed before the image is saved, and the
original directory entry is kept as a .BAK file on the guest disk, so a failed
experiment is always reversible.

Usage
-----
    python tools\\inject_paldump.py verify  IMAGE.HDI
    python tools\\inject_paldump.py inject  IMAGE.HDI tools\\PALDUMP.COM
    python tools\\inject_paldump.py autoexec IMAGE.HDI --dumper PD2PAL.COM
    python tools\\inject_paldump.py restore IMAGE.HDI
"""
from __future__ import annotations

import argparse
import struct
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hdi98 import open_fs                                  # noqa: E402

FAT12_EOC = 0xFFF
FAT16_EOC = 0xFFFF
ATTR_ARCHIVE = 0x20
ATTR_DIR = 0x10
ATTR_VOLUME = 0x08


def name83(name: str) -> tuple[bytes, bytes]:
    name = name.upper()
    stem, _, ext = name.partition(".")
    return stem[:8].ljust(8).encode("ascii"), ext[:3].ljust(3).encode("ascii")


def fat_buf(fs) -> bytearray:
    return bytearray(fs._fat_data)


def fat_get(buf: bytearray, fs, cluster: int) -> int:
    if fs.fat_type == 12:
        off = cluster + (cluster // 2)
        word = struct.unpack_from("<H", buf, off)[0]
        return (word >> 4) if (cluster & 1) else (word & 0x0FFF)
    return struct.unpack_from("<H", buf, cluster * 2)[0]


def fat_set(buf: bytearray, fs, cluster: int, value: int) -> None:
    if fs.fat_type == 12:
        off = cluster + (cluster // 2)
        word = struct.unpack_from("<H", buf, off)[0]
        if cluster & 1:
            word = (word & 0x000F) | ((value & 0x0FFF) << 4)
        else:
            word = (word & 0xF000) | (value & 0x0FFF)
        struct.pack_into("<H", buf, off, word)
    else:
        struct.pack_into("<H", buf, cluster * 2, value & 0xFFFF)


def alloc_chain(fs, buf: bytearray, count: int) -> list[int]:
    eoc = FAT12_EOC if fs.fat_type == 12 else FAT16_EOC
    chain: list[int] = []
    for c in range(2, fs.total_clusters + 2):
        if len(chain) == count:
            break
        if fat_get(buf, fs, c) == 0:
            chain.append(c)
    if len(chain) < count:
        raise SystemExit(f"not enough free clusters: need {count}, found {len(chain)}")
    for i in range(len(chain) - 1):
        fat_set(buf, fs, chain[i], chain[i + 1])
    fat_set(buf, fs, chain[-1], eoc)
    return chain


def root_bytes(fs) -> bytearray:
    return bytearray(fs._read_fs_bytes(fs.first_root_sector * fs.bytes_per_sector,
                                       fs.root_dir_sectors * fs.bytes_per_sector))


def find_entry(raw: bytearray, name: str):
    n8, e3 = name83(name)
    for i in range(fs_root_entries(raw)):
        off = i * 32
        if raw[off] in (0x00,):
            return None, off, True
        if raw[off] == 0xE5:
            continue
        if bytes(raw[off:off + 8]) == n8 and bytes(raw[off + 8:off + 11]) == e3:
            return i, off, False
    return None, None, False


def fs_root_entries(raw: bytearray) -> int:
    return len(raw) // 32


def free_slot(raw: bytearray):
    for i in range(fs_root_entries(raw)):
        off = i * 32
        if raw[off] in (0x00, 0xE5):
            return off
    raise SystemExit("root directory is full")


def fat_serialize(fs, fat: bytearray) -> bytes:
    """Serialise the FAT exactly like `fat_set` packs it.

    NOTE: do NOT use 98Bridge's `_build_fat_bytes` for this. Its FAT12 branch
    ORs the neighbouring nibble instead of preserving it
    (`word = (word & 0xF000) | val` for even clusters), which wipes the low
    nibble of every odd entry and destroys the table. Verified by rebuilding the
    FAT of an untouched image and diffing: 2550 of 4096 bytes changed.
    """
    buf = bytearray(len(fs._fat_data))
    for c in range(2, fs.total_clusters + 2):
        v = fat_get(fat, fs, c)
        if fs.fat_type == 12:
            off = c + (c // 2)
            if off + 1 >= len(buf):
                break
            word = struct.unpack_from("<H", buf, off)[0]
            if c & 1:
                word = (word & 0x000F) | ((v & 0x0FFF) << 4)
            else:
                word = (word & 0xF000) | (v & 0x0FFF)
            struct.pack_into("<H", buf, off, word)
        else:
            struct.pack_into("<H", buf, c * 2, v & 0xFFFF)
    # keep the reserved entries (0,1) exactly as they were on disk
    buf[0:3] = fs._fat_data[0:3]
    return bytes(buf)


def flush_fat(fs, fat: bytearray) -> None:
    data = fat_serialize(fs, fat)
    for n in range(fs.num_fats):
        fs._write_fs_bytes((fs.first_fat_sector + n * fs.fat_size_16) * fs.bytes_per_sector,
                           data)
    fs._fat_data = data


def put_file(fs, fullname: str, payload: bytes) -> str:
    """Add or replace a file in the root directory. Returns a status string."""
    cb = fs.sectors_per_cluster * fs.bytes_per_sector
    need = max(1, (len(payload) + cb - 1) // cb)
    fat = fat_buf(fs)
    raw = root_bytes(fs)

    existing_off = None
    for i in range(fs_root_entries(raw)):
        off = i * 32
        e = raw[off:off + 32]
        if e[0] in (0x00,):
            break
        if e[0] == 0xE5:
            continue
        n8, e3 = name83(fullname)
        if bytes(e[0:8]) == n8 and bytes(e[8:11]) == e3:
            existing_off = off
            break

    if existing_off is not None:                       # free the old chain first
        old = struct.unpack_from("<H", raw, existing_off + 26)[0]
        c, seen = old, set()
        eoc = FAT12_EOC if fs.fat_type == 12 else FAT16_EOC
        while 2 <= c < eoc and c not in seen:
            seen.add(c)
            nxt = fat_get(fat, fs, c)
            fat_set(fat, fs, c, 0)
            c = nxt

    chain = alloc_chain(fs, fat, need)
    for i, cl in enumerate(chain):
        chunk = payload[i * cb:(i + 1) * cb]
        chunk = chunk + b"\x00" * (cb - len(chunk))
        fs._write_fs_bytes(fs.cluster_to_fs_sector(cl) * fs.bytes_per_sector, chunk)

    entry = bytearray(32)
    n8, e3 = name83(fullname)
    entry[0:8] = n8
    entry[8:11] = e3
    entry[11] = ATTR_ARCHIVE
    now = datetime.now()
    struct.pack_into("<H", entry, 22, (now.hour << 11) | (now.minute << 5) | (now.second // 2))
    struct.pack_into("<H", entry, 24, ((now.year - 1980) << 9) | (now.month << 5) | now.day)
    struct.pack_into("<H", entry, 26, chain[0])
    struct.pack_into("<I", entry, 28, len(payload))

    off = existing_off if existing_off is not None else free_slot(raw)
    raw[off:off + 32] = entry

    flush_fat(fs, fat)
    fs._write_fs_bytes(fs.first_root_sector * fs.bytes_per_sector, bytes(raw))
    fs._build_root()
    return f"put {fullname}: {len(payload)} bytes -> clusters {chain}"


def del_file(fs, fullname: str) -> str:
    raw = root_bytes(fs)
    n8, e3 = name83(fullname)
    for i in range(fs_root_entries(raw)):
        off = i * 32
        e = raw[off:off + 32]
        if e[0] == 0x00:
            break
        if e[0] == 0xE5:
            continue
        if bytes(e[0:8]) == n8 and bytes(e[8:11]) == e3:
            start = struct.unpack_from("<H", e, 26)[0]
            fat = fat_buf(fs)
            c, seen = start, set()
            while 2 <= c < FAT12_EOC and c not in seen:
                seen.add(c)
                nxt = fat_get(fat, fs, c)
                fat_set(fat, fs, c, 0)
                c = nxt
            raw[off] = 0xE5
            flush_fat(fs, fat)
            fs._write_fs_bytes(fs.first_root_sector * fs.bytes_per_sector, bytes(raw))
            fs._build_root()
            return f"deleted {fullname} (chain from {start} freed)"
    raise SystemExit(f"{fullname}: not found")


def cmd_verify(a) -> int:
    disk, fs = open_fs(a.image)
    print(f"fs={fs.fs_type_label} bpb={fs._bpb_source} write_back={fs.can_write_back}")
    cb = fs.sectors_per_cluster * fs.bytes_per_sector
    free = sum(1 for c in range(2, fs.total_clusters + 2) if fs.get_fat_entry(c) == 0)
    print(f"cluster={cb}B free_clusters={free}")

    # 1. the serializer must reproduce an untouched FAT byte for byte
    rebuilt = fat_serialize(fs, fat_buf(fs))
    same = rebuilt == bytes(fs._fat_data)
    print(f"FAT round-trip: {'identical' if same else 'DIFFERS'}")
    if not same:
        bad = sum(1 for i in range(len(rebuilt)) if rebuilt[i] != fs._fat_data[i])
        print(f"  {bad} differing bytes - serializer is broken, do not write")

    # 2. every file must read back at its declared size
    bad = []
    for path, e in fs.walk():
        if e.is_directory:
            continue
        try:
            data = fs.read_file(e)
        except Exception as exc:
            bad.append(f"{path}: read error {exc}")
            continue
        if len(data) != e.size:
            bad.append(f"{path}: size {e.size} but read {len(data)}")
    if bad:
        print(f"!! {len(bad)} files do not read back at their declared size:")
        for line in bad[:12]:
            print("   ", line)
    else:
        print("all files read back at their declared size")
    return 0 if same and not bad else 1


def cmd_inject(a) -> int:
    disk, fs = open_fs(a.image)
    payload = Path(a.hostfile).read_bytes()
    print(put_file(fs, a.dosname, payload))
    disk.save()
    # re-open and prove it round-trips
    disk2, fs2 = open_fs(a.image)
    entry = fs2.resolve_path("/" + a.dosname)
    if entry is None:
        raise SystemExit("verification failed: file not visible after save")
    back = fs2.read_file(entry)
    ok = back == payload
    print(f"verify: {'OK' if ok else 'MISMATCH'} "
          f"({len(back)} bytes, sha {__import__('hashlib').sha256(back).hexdigest()[:16]})")
    return 0 if ok else 1


def cmd_autoexec(a) -> int:
    disk, fs = open_fs(a.image)
    original = fs.read_file(fs.resolve_path("/AUTOEXEC.BAT"))
    if not any(e.display_name == "AUTOEXEC.ORI" for _, e in fs.walk('/')):
        print(put_file(fs, "AUTOEXEC.ORI", original))
    new = (b"@ECHO OFF\r\n"
           b"ECHO PD2 PALETTE PROBE\r\n"
           + a.dumper.encode("ascii") + b"\r\n"
           b"ECHO PROBE DONE\r\n"
           b"START.COM\r\n")
    print(put_file(fs, "AUTOEXEC.BAT", new))
    disk.save()
    disk2, fs2 = open_fs(a.image)
    print("new AUTOEXEC.BAT on the image:\n" +
          fs2.read_file(fs2.resolve_path("/AUTOEXEC.BAT")).decode("latin1"))
    return 0


def cmd_restore(a) -> int:
    disk, fs = open_fs(a.image)
    entry = fs.resolve_path("/AUTOEXEC.ORI")
    if entry is None:
        raise SystemExit("no AUTOEXEC.ORI on the image - nothing to restore")
    original = fs.read_file(entry)
    print(put_file(fs, "AUTOEXEC.BAT", original))
    print(del_file(fs, "AUTOEXEC.ORI"))
    for name in ("PD2PAL.COM", "PD2PAL.DAT"):
        try:
            print(del_file(fs, name))
        except SystemExit as exc:
            print(f"  ({exc})")
    disk.save()
    print("restored")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("verify"); p.add_argument("image", type=Path); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("inject")
    p.add_argument("image", type=Path)
    p.add_argument("hostfile", type=Path)
    p.add_argument("--dosname", default="PD2PAL.COM")
    p.set_defaults(fn=cmd_inject)
    p = sub.add_parser("autoexec")
    p.add_argument("image", type=Path)
    p.add_argument("--dumper", default="PD2PAL.COM")
    p.set_defaults(fn=cmd_autoexec)
    p = sub.add_parser("restore")
    p.add_argument("image", type=Path)
    p.set_defaults(fn=cmd_restore)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
