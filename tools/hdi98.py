"""Open the Power Dolls 2 HDI with 98Bridge's FAT parser.

98Bridge (https://github.com/... — the local 98Bridge-main checkout) has a FAT12/FAT16
reader and a write-back path. This wrapper exposes just what the palette dumper
needs:

    python tools\\hdi98.py list  _hdi_test\\pd2s_test.hdi
    python tools\\hdi98.py get   _hdi_test\\pd2s_test.hdi /PD2D/GO.EXE -o out\\go.exe

(the write path is exercised by tools\\inject_paldump.py)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent.parent / "98Bridge-main"
if not BRIDGE.is_dir():
    raise SystemExit(f"98Bridge checkout not found at {BRIDGE}")


def open_fs(image: Path):
    """Return (disk_image, FATFilesystem) for a PC-98 HDI/FDI/raw image.

    98Bridge registers its formats through plugins, so the core format plugin
    has to be imported before open_image() knows about .hdi.
    """
    sys.path.insert(0, str(BRIDGE))
    sys.path.insert(0, str(BRIDGE / "plugins" / "core"))
    from disk_image import open_image                     # noqa: E402
    from fat_fs import FATFilesystem                      # noqa: E402
    import pc98_formats                                   # noqa: F401,E402  (registers formats)

    disk = open_image(str(image))
    fs = FATFilesystem(disk)
    return disk, fs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["list", "get", "tree", "info"])
    ap.add_argument("image", type=Path)
    ap.add_argument("path", nargs="?")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args()

    disk, fs = open_fs(a.image)
    print(f"image : {a.image}")
    print(f"format: {type(disk).__name__}  label={getattr(disk, 'label', '?')}")
    print(f"disk  : {disk.sector_size} B/sector, {disk.total_sectors} sectors")
    print(f"fs    : {fs.fs_type_label}  bpb_source={fs._bpb_source}  "
          f"write_back={fs.can_write_back} {fs.write_back_status}")
    if not fs.bpb_is_valid:
        print("!! BPB was not read from the disk - do NOT trust writes")

    if a.action == "info":
        return 0
    if a.action == "list":
        for path, entry in fs.walk():
            if entry.is_directory:
                continue
            print(f"{entry.size:>9}  {path}")
        return 0
    if a.action == "tree":
        for path, entry in fs.walk():
            kind = "DIR " if entry.is_directory else "    "
            size = "" if entry.is_directory else entry.size
            print(f"{kind}{path}  {size}")
        return 0
    if a.action == "get":
        entry = fs.resolve_path(a.path)
        if entry is None:
            raise SystemExit(f"{a.path}: not found")
        data = fs.read_file(entry)
        dst = a.out or Path(Path(a.path).name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        print(f"extracted {a.path} -> {dst} ({len(data)} bytes)")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
