"""Put a custom AUTOEXEC.BAT on the PD2 HDI copy that runs the palette dumper
straight off the host via DOSBox-X's Z: drive.

Z: is DOSBox-X's built-in drive mapped to the emulator's -working-dir, so a file
the guest writes to Z:\\ lands on the host immediately - no image write-back and
no clean exit required. PALDUMP.COM accepts a full path as its argument, so the
whole dump is one batch line.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hdi98 import open_fs                                   # noqa: E402
from inject_paldump import put_file, del_file               # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--dumper", default="Z:\\PALDUMP.COM")
    ap.add_argument("--outfile", default="Z:\\PD2PAL.DAT")
    a = ap.parse_args()

    disk, fs = open_fs(a.image)
    original = fs.read_file(fs.resolve_path("/AUTOEXEC.BAT"))
    if not any(e.display_name == "AUTOEXEC.ORI" for _, e in fs.walk('/')):
        print(put_file(fs, "AUTOEXEC.ORI", original))

    lines = [
        "@ECHO OFF",
        "ECHO PD2 PALETTE PROBE",
        "DIR Z:\\",
        f"{a.dumper} {a.outfile}",
        "ECHO PROBE DONE",
        "START.COM",
    ]
    new = ("\r\n".join(lines) + "\r\n").encode("ascii")
    print(put_file(fs, "AUTOEXEC.BAT", new))
    disk.save()
    disk2, fs2 = open_fs(a.image)
    print("--- AUTOEXEC.BAT now ---")
    print(fs2.read_file(fs2.resolve_path("/AUTOEXEC.BAT")).decode("latin1"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
